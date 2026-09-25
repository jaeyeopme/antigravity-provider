from __future__ import annotations

import hashlib
import json
import os
import tempfile
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from .models import DEFAULT_MODEL, normalize_effort, normalize_model_id, strip_provider_prefix

CATALOG_TTL_SECONDS = 4 * 60 * 60
_SUFFIXES = (
    ("extra-low", "low"),
    ("extra-high", "high"),
    ("thinking", "high"),
    ("minimal", "minimal"),
    ("medium", "medium"),
    ("high", "high"),
    ("low", "low"),
)
_RUNTIME_ALIASES = {
    "gemini-pro-agent": ("gemini-3.1-pro", "high"),
    "gemini-3-flash-agent": ("gemini-3.5-flash", "high"),
}


@dataclass(frozen=True)
class RouteSpec:
    wire_model: str
    model_enum: str | None = None
    max_output_tokens: int = 65535
    supports_thinking: bool | None = None
    thinking_budget: int | None = None
    used_non_gemini_model: bool = False


@dataclass(frozen=True)
class ResolvedRoute:
    public_model: str
    wire_model: str
    model_enum: str | None
    max_output_tokens: int
    thinking_budget: int | None
    include_thoughts: bool
    used_non_gemini_model: bool


@dataclass
class _ModelGroup:
    public_id: str
    variants: dict[str, RouteSpec] = field(default_factory=dict)
    default: RouteSpec | None = None
    tiered: RouteSpec | None = None
    advertised_variants: set[str] = field(default_factory=set)
    tiered_advertised: bool = False


@dataclass
class ModelCatalog:
    groups: dict[str, _ModelGroup]
    runtime_routes: dict[str, RouteSpec]
    runtime_to_public: dict[str, str]
    default_model: str = DEFAULT_MODEL
    fallback_groups: dict[str, _ModelGroup] = field(default_factory=dict)

    def model_ids(self) -> list[str]:
        return [normalize_model_id(model) for model in sorted(self.groups)]

    def resolve(self, model: str, effort: str | None = None) -> ResolvedRoute:
        requested = strip_provider_prefix(normalize_model_id(model))
        level = normalize_effort(effort)
        public_id = self.runtime_to_public.get(requested, requested)
        group = self.groups.get(public_id) or self.fallback_groups.get(public_id)

        if requested in self.runtime_routes and requested != public_id:
            spec = self.runtime_routes[requested]
            return _resolved(public_id, spec, level, tiered=False)
        if group is None:
            spec = RouteSpec(wire_model=requested)
            return _resolved(requested, spec, level, tiered=False)

        if group.tiered is not None:
            return _resolved(public_id, group.tiered, level, tiered=True)
        spec = _pick_variant(group, level)
        return _resolved(public_id, spec, level, tiered=False)

    def max_tokens(self, model: str) -> int:
        return self.resolve(model, "low").max_output_tokens


def _pick_variant(group: _ModelGroup, effort: str) -> RouteSpec:
    orders = {
        "off": ("low", "minimal", "medium", "high"),
        "minimal": ("minimal", "low", "medium", "high"),
        "low": ("low", "minimal", "medium", "high"),
        "medium": ("medium", "low", "high", "minimal"),
        "high": ("high", "medium", "low", "minimal"),
    }
    for level in orders[effort]:
        if level in group.variants:
            return group.variants[level]
    if group.default is not None:
        return group.default
    if group.variants:
        return next(iter(group.variants.values()))
    return RouteSpec(group.public_id)


def _thinking_budget(public_id: str, spec: RouteSpec, effort: str, *, tiered: bool) -> int | None:
    if spec.supports_thinking is False:
        return None
    if spec.supports_thinking is not True and spec.thinking_budget is None:
        return None
    if effort == "off":
        return 0
    if not tiered and spec.thinking_budget is not None:
        return spec.thinking_budget
    if public_id == "gemini-3.1-pro":
        return 10001 if effort == "high" else 1001
    if public_id.startswith("gemini-"):
        return {"minimal": 1000, "low": 1000, "medium": 4000, "high": -1}[effort]
    if spec.thinking_budget is not None:
        return spec.thinking_budget
    if public_id.startswith("claude-"):
        return 1024
    if public_id.startswith("gpt-oss-"):
        return 8192
    return None


def _resolved(public_id: str, spec: RouteSpec, effort: str, *, tiered: bool) -> ResolvedRoute:
    budget = _thinking_budget(public_id, spec, effort, tiered=tiered)
    return ResolvedRoute(
        public_model=normalize_model_id(public_id),
        wire_model=spec.wire_model,
        model_enum=spec.model_enum,
        max_output_tokens=spec.max_output_tokens,
        thinking_budget=budget,
        include_thoughts=budget is not None and effort != "off",
        used_non_gemini_model=spec.used_non_gemini_model,
    )


def _route_spec(runtime_id: str, info: dict[str, Any]) -> RouteSpec:
    maximum = info.get("maxOutputTokens")
    budget = info.get("thinkingBudget")
    return RouteSpec(
        wire_model=runtime_id,
        model_enum=info.get("model") if isinstance(info.get("model"), str) else None,
        max_output_tokens=maximum if isinstance(maximum, int) and maximum > 0 else 65535,
        supports_thinking=info.get("supportsThinking") if isinstance(info.get("supportsThinking"), bool) else None,
        thinking_budget=budget if isinstance(budget, int) else None,
        used_non_gemini_model=bool(info.get("usedNonGeminiModel") or runtime_id.startswith("gpt-oss-")),
    )


def _collect_runtime_ids(value: Any, known: set[str], found: set[str]) -> None:
    if isinstance(value, str):
        if value in known:
            found.add(value)
        return
    if isinstance(value, dict):
        for key, nested in value.items():
            if key in known:
                found.add(key)
            _collect_runtime_ids(nested, known, found)
    elif isinstance(value, list):
        for nested in value:
            _collect_runtime_ids(nested, known, found)


def _selectable(runtime_id: str, info: dict[str, Any], advertised: set[str]) -> bool:
    lower = runtime_id.lower()
    if info.get("isInternal") is True or "image" in lower or lower.startswith(("chat_", "tab_", "model_")):
        return False
    if not runtime_id or any(char.isspace() for char in runtime_id):
        return False
    return runtime_id in advertised or lower.startswith(("gemini-", "claude-", "gpt-oss-"))


def _suffix(runtime_id: str) -> tuple[str, str] | None:
    lower = runtime_id.lower()
    for suffix, effort in _SUFFIXES:
        marker = f"-{suffix}"
        if lower.endswith(marker):
            return runtime_id[: -len(marker)], effort
    return None


def build_catalog(payload: dict[str, Any], fallback: ModelCatalog | None = None) -> ModelCatalog:
    raw_models = payload.get("models") if isinstance(payload, dict) else None
    if not isinstance(raw_models, dict):
        raw_models = {}
    known = {key for key, value in raw_models.items() if isinstance(key, str) and isinstance(value, dict)}
    advertised: set[str] = set()
    _collect_runtime_ids(payload.get("agentModelSorts"), known, advertised)
    _collect_runtime_ids(payload.get("tieredModelIds"), known, advertised)

    groups: dict[str, _ModelGroup] = {}
    runtime_routes: dict[str, RouteSpec] = {}
    runtime_to_public: dict[str, str] = {}

    for runtime_id, raw_info in raw_models.items():
        if not isinstance(runtime_id, str) or not isinstance(raw_info, dict):
            continue
        if not _selectable(runtime_id, raw_info, advertised):
            continue
        spec = _route_spec(runtime_id, raw_info)
        runtime_routes[runtime_id] = spec
        is_advertised = runtime_id in advertised

        if runtime_id.endswith("-tiered"):
            public_id = runtime_id[: -len("-tiered")]
            group = groups.setdefault(public_id, _ModelGroup(public_id))
            if group.tiered is None or is_advertised:
                group.tiered = spec
                group.tiered_advertised = is_advertised
        elif runtime_id in _RUNTIME_ALIASES:
            public_id, effort = _RUNTIME_ALIASES[runtime_id]
            group = groups.setdefault(public_id, _ModelGroup(public_id))
            if effort not in group.advertised_variants:
                group.variants[effort] = spec
            if is_advertised:
                group.variants[effort] = spec
                group.advertised_variants.add(effort)
        elif parsed := _suffix(runtime_id):
            public_id, effort = parsed
            group = groups.setdefault(public_id, _ModelGroup(public_id))
            if effort not in group.advertised_variants:
                group.variants[effort] = spec
            if is_advertised:
                group.variants[effort] = spec
                group.advertised_variants.add(effort)
        else:
            public_id = runtime_id
            group = groups.setdefault(public_id, _ModelGroup(public_id))
            group.default = spec
        runtime_to_public[runtime_id] = public_id

    for group in groups.values():
        if group.tiered is not None and not group.tiered_advertised and group.advertised_variants:
            group.tiered = None

    raw_default = payload.get("defaultAgentModelId") or payload.get("defaultAgentModel")
    default_public = runtime_to_public.get(str(raw_default), str(raw_default)) if raw_default else ""
    default_model = normalize_model_id(default_public) if default_public in groups else DEFAULT_MODEL
    return ModelCatalog(
        groups=groups,
        runtime_routes={**(fallback.runtime_routes if fallback else {}), **runtime_routes},
        runtime_to_public={**(fallback.runtime_to_public if fallback else {}), **runtime_to_public},
        default_model=default_model,
        fallback_groups=(fallback.groups if fallback else {}),
    )


_SEED_PAYLOAD = {
    "models": {
        "gemini-3.8-flash-tiered": {"model": "MODEL_PLACEHOLDER_M322", "maxOutputTokens": 65536, "supportsThinking": True, "thinkingBudget": -1},
        "gemini-3.7-flash-tiered": {"model": "MODEL_PLACEHOLDER_M301", "maxOutputTokens": 65536, "supportsThinking": True, "thinkingBudget": -1},
        "gemini-3.6-flash-high": {"model": "MODEL_PLACEHOLDER_M71", "maxOutputTokens": 65536, "supportsThinking": True, "thinkingBudget": -1},
        "gemini-3.6-flash-medium": {"model": "MODEL_PLACEHOLDER_M72", "maxOutputTokens": 65536, "supportsThinking": True, "thinkingBudget": 4000},
        "gemini-3.6-flash-low": {"model": "MODEL_PLACEHOLDER_M73", "maxOutputTokens": 65536, "supportsThinking": True, "thinkingBudget": 1000},
        "gemini-3.1-pro-low": {"model": "MODEL_PLACEHOLDER_M36", "maxOutputTokens": 65535, "supportsThinking": True, "thinkingBudget": 1001},
        "gemini-pro-agent": {"model": "MODEL_PLACEHOLDER_M16", "maxOutputTokens": 65535, "supportsThinking": True, "thinkingBudget": 10001},
        "gemini-3.5-flash-extra-low": {"model": "MODEL_PLACEHOLDER_M187", "maxOutputTokens": 65536, "supportsThinking": True, "thinkingBudget": 1000},
        "gemini-3.5-flash-low": {"model": "MODEL_PLACEHOLDER_M20", "maxOutputTokens": 65536, "supportsThinking": True, "thinkingBudget": 4000},
        "gemini-3-flash-agent": {"model": "MODEL_PLACEHOLDER_M132", "maxOutputTokens": 65536, "supportsThinking": True, "thinkingBudget": 10000},
        "claude-sonnet-4-6": {"maxOutputTokens": 64000, "supportsThinking": True, "thinkingBudget": 1024},
        "claude-opus-4-6-thinking": {"maxOutputTokens": 64000, "supportsThinking": True, "thinkingBudget": 1024},
        "gpt-oss-120b-medium": {"model": "MODEL_OPENAI_GPT_OSS_120B_MEDIUM", "maxOutputTokens": 32768, "supportsThinking": True, "thinkingBudget": 8192, "usedNonGeminiModel": True},
    },
    "defaultAgentModelId": "gemini-3.1-pro-low",
}
_FALLBACK_CATALOG = build_catalog(_SEED_PAYLOAD)


def fallback_catalog() -> ModelCatalog:
    return _FALLBACK_CATALOG


def _default_catalog_path() -> Path:
    root = Path(os.getenv("HERMES_HOME") or Path.home() / ".hermes").expanduser()
    return root / ".antigravity_models.json"


class CatalogManager:
    def __init__(
        self,
        *,
        path: Path | None = None,
        ttl_seconds: float = CATALOG_TTL_SECONDS,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self.path = Path(path or _default_catalog_path()).expanduser()
        self.ttl_seconds = ttl_seconds
        self.clock = clock
        self._lock = threading.Lock()
        self._entries: dict[str, tuple[float, ModelCatalog, dict[str, Any]]] = {}
        self._current = fallback_catalog()

    @staticmethod
    def _project_key(project_id: str) -> str:
        return hashlib.sha256(project_id.encode("utf-8")).hexdigest()

    def current(self) -> ModelCatalog:
        return self._current

    def _load(self, project_key: str) -> tuple[float, ModelCatalog, dict[str, Any]] | None:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (FileNotFoundError, OSError, ValueError):
            return None
        if not isinstance(data, dict):
            return None
        payload = data.get("payload")
        checked_at = data.get("checked_at")
        if data.get("version") != 1 or data.get("project") != project_key:
            return None
        if not isinstance(payload, dict) or not isinstance(checked_at, (int, float)):
            return None
        catalog = build_catalog(payload, fallback_catalog())
        if not catalog.groups:
            return None
        return float(checked_at), catalog, payload

    def _save(self, project_key: str, checked_at: float, payload: dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        try:
            os.chmod(self.path.parent, 0o700)
        except OSError:
            pass
        fd, temporary = tempfile.mkstemp(prefix=f".{self.path.name}.", dir=str(self.path.parent), text=True)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump({"version": 1, "project": project_key, "checked_at": checked_at, "payload": payload}, handle, sort_keys=True)
                handle.write("\n")
            os.chmod(temporary, 0o600)
            os.replace(temporary, self.path)
            os.chmod(self.path, 0o600)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)

    def get(
        self,
        *,
        client: Any,
        access_token: str,
        project_id: str,
        force: bool = False,
    ) -> ModelCatalog:
        project_key = self._project_key(project_id)
        with self._lock:
            entry = self._entries.get(project_key)
            if entry is None:
                entry = self._load(project_key)
                if entry is not None:
                    self._entries[project_key] = entry
            now = self.clock()
            if entry is not None and not force and now - entry[0] < self.ttl_seconds:
                self._current = entry[1]
                return entry[1]
            try:
                payload = client.fetch_available_models(access_token=access_token, project_id=project_id)
                catalog = build_catalog(payload, fallback_catalog())
                if not catalog.groups:
                    raise ValueError("empty Antigravity model catalog")
            except Exception:
                if entry is not None:
                    self._current = entry[1]
                    return entry[1]
                self._current = fallback_catalog()
                return self._current
            checked_at = self.clock()
            saved = (checked_at, catalog, payload)
            self._entries[project_key] = saved
            self._current = catalog
            self._save(project_key, checked_at, payload)
            return catalog


catalog_manager = CatalogManager()
