from __future__ import annotations

import threading
import time
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Iterable

from .antigravity_client import AntigravityClient
from .catalog import ModelCatalog, catalog_manager
from .cloudcode import load_or_onboard_project
from .credentials import CredentialStore, load_agy_keychain_credentials
from .errors import ProxyError, TokenExpired
from .oauth import refresh_access_token
from .openai_compat import ChatRequest, parse_chat_request, to_openai_completion, to_openai_stream_chunks
from .transform import build_generate_content_request

_credential_lock = threading.Lock()
_keychain_credentials: dict[str, Any] | None = None


def clear_credential_cache() -> None:
    global _keychain_credentials
    with _credential_lock:
        _keychain_credentials = None


def _has_credentials(credentials: dict[str, Any]) -> bool:
    return bool(
        credentials.get("access_token")
        or credentials.get("access")
        or credentials.get("token")
        or credentials.get("refresh_token")
        or credentials.get("refresh")
    )


def _prepare_credentials(credentials: dict[str, Any]) -> tuple[dict[str, Any], bool]:
    creds = dict(credentials)
    dirty = False
    access = creds.get("access_token") or creds.get("access") or creds.get("token")
    refresh = creds.get("refresh_token") or creds.get("refresh")
    expires = creds.get("expires_at") or creds.get("expires")
    if refresh and (not access or (isinstance(expires, (int, float)) and time.time() + 60 >= float(expires))):
        creds.update(refresh_access_token(str(refresh)))
        access = creds["access_token"]
        dirty = True
    project = creds.get("project_id") or creds.get("projectId")
    if not project:
        if not access:
            raise ProxyError(
                "Missing access token for Antigravity project discovery",
                status=401,
                error_type="invalid_request_error",
            )
        project = load_or_onboard_project(str(access))
        creds["project_id"] = project
        dirty = True
    return creds, dirty


def _public_credentials(credentials: dict[str, Any], source: str) -> dict[str, Any]:
    access = credentials.get("access_token") or credentials.get("access") or credentials.get("token")
    refresh = credentials.get("refresh_token") or credentials.get("refresh")
    project = credentials.get("project_id") or credentials.get("projectId")
    return {
        "access_token": str(access or ""),
        "refresh_token": str(refresh or ""),
        "project_id": str(project or ""),
        "source": source,
    }


def load_antigravity_credentials(store: Any | None = None) -> dict[str, Any]:
    """Browser OAuth is an explicit profile override; Keychain is the fallback."""
    global _keychain_credentials
    store = store or CredentialStore.default()
    stored = store.load()
    if isinstance(stored, dict) and _has_credentials(stored):
        creds, dirty = _prepare_credentials(stored)
        if dirty:
            store.save(creds)
        return _public_credentials(creds, "store")

    with _credential_lock:
        if _keychain_credentials is None:
            loaded = load_agy_keychain_credentials()
            _keychain_credentials = dict(loaded) if loaded else {}
        if not _has_credentials(_keychain_credentials):
            raise ProxyError(
                "Missing Antigravity credentials. Run `hermes agy login`.",
                status=401,
                error_type="invalid_request_error",
            )
        creds, _ = _prepare_credentials(_keychain_credentials)
        _keychain_credentials = creds
        return _public_credentials(creds, "agy-keychain")


def _refresh_expired_credentials(credentials: dict[str, Any], store: Any) -> str:
    global _keychain_credentials
    refresh = credentials.get("refresh_token")
    if not refresh:
        raise TokenExpired()
    refreshed = refresh_access_token(str(refresh))
    if credentials.get("source") == "store":
        saved = store.load()
        saved.update(refreshed)
        store.save(saved)
    else:
        with _credential_lock:
            cached = dict(_keychain_credentials or {})
            cached.update(refreshed)
            _keychain_credentials = cached
    return str(refreshed["access_token"])


def load_model_catalog(*, force: bool = False, store: Any | None = None) -> ModelCatalog:
    credentials = load_antigravity_credentials(store)
    return catalog_manager.get(
        client=AntigravityClient(),
        access_token=credentials["access_token"],
        project_id=credentials["project_id"],
        force=force,
    )


def build_upstream_body(
    request: ChatRequest,
    *,
    client: Any | None = None,
    store: Any | None = None,
    session_id: str | None = None,
    catalog: ModelCatalog | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    credentials = load_antigravity_credentials(store)
    if catalog is None:
        if client is not None and hasattr(client, "fetch_available_models"):
            catalog = catalog_manager.get(
                client=client,
                access_token=credentials["access_token"],
                project_id=credentials["project_id"],
            )
        else:
            catalog = catalog_manager.current()
    body = build_generate_content_request(
        model=request.model,
        project_id=credentials["project_id"],
        messages=request.messages,
        tools=request.tools,
        reasoning_effort=request.reasoning_effort,
        max_tokens=request.max_tokens,
        temperature=request.temperature,
        top_p=request.top_p,
        tool_choice=request.tool_choice,
        session_id=session_id,
        catalog=catalog,
    )
    return body, credentials


def generate_chat_completion(
    payload: dict[str, Any],
    *,
    client: Any | None = None,
    store: Any | None = None,
    session_id: str | None = None,
) -> dict[str, Any]:
    request = parse_chat_request(payload)
    client = client or AntigravityClient()
    store = store or CredentialStore.default()
    body, credentials = build_upstream_body(request, client=client, store=store, session_id=session_id)
    try:
        upstream = client.generate(access_token=credentials["access_token"], body=body)
    except TokenExpired:
        access_token = _refresh_expired_credentials(credentials, store)
        upstream = client.generate(access_token=access_token, body=body)
    return to_openai_completion(request.model, upstream)


def stream_chat_completion(
    payload: dict[str, Any],
    *,
    client: Any | None = None,
    store: Any | None = None,
    session_id: str | None = None,
) -> Iterable[SimpleNamespace]:
    request = parse_chat_request(payload)
    client = client or AntigravityClient()
    store = store or CredentialStore.default()
    body, credentials = build_upstream_body(request, client=client, store=store, session_id=session_id)

    def upstream_events() -> Iterable[dict[str, Any]]:
        emitted = False
        try:
            for event in client.stream_generate(access_token=credentials["access_token"], body=body):
                emitted = True
                yield event
        except TokenExpired:
            if emitted:
                raise
            access_token = _refresh_expired_credentials(credentials, store)
            yield from client.stream_generate(access_token=access_token, body=body)

    def chunks() -> Iterable[SimpleNamespace]:
        emitted = False
        for value in to_openai_stream_chunks(request.model, upstream_events()):
            emitted = True
            yield _namespace(value)
        if not emitted:
            raise ProxyError("Antigravity returned an empty stream", status=502)

    return chunks()


def _namespace(value: Any) -> Any:
    if isinstance(value, dict):
        return SimpleNamespace(**{key: _namespace(nested) for key, nested in value.items()})
    if isinstance(value, list):
        return [_namespace(nested) for nested in value]
    return value


def openai_completion_object(completion: dict[str, Any]) -> SimpleNamespace:
    completion = dict(completion)
    choices = []
    for raw_choice in completion.get("choices") or []:
        choice = dict(raw_choice)
        message = dict(choice.get("message") or {})
        message.setdefault("content", None)
        message.setdefault("tool_calls", None)
        choice["message"] = message
        choices.append(choice)
    completion["choices"] = choices
    completion.setdefault("usage", {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0})
    return _namespace(completion)


class HermesAntigravityClient:
    """OpenAI-client-compatible facade over Antigravity's native protocol."""

    HERMES_SKIP_TRANSPORT_WRAP = True

    def __init__(self, *, api_key: str = "", base_url: str = "", **_: Any) -> None:
        self.api_key = api_key
        self.base_url = base_url
        self.is_closed = False
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create_chat_completion))

    def close(self) -> None:
        self.is_closed = True

    def _create_chat_completion(
        self,
        *,
        model: str,
        messages: list[dict[str, Any]] | None = None,
        stream: bool = False,
        _antigravity_session_id: str | None = None,
        **kwargs: Any,
    ) -> Any:
        payload = {"model": model, "messages": messages or [], **kwargs}
        if stream:
            return stream_chat_completion(payload, session_id=_antigravity_session_id)
        completion = generate_chat_completion(payload, session_id=_antigravity_session_id)
        return openai_completion_object(completion)


def ensure_provider_profile_files(root: Path | None = None) -> Path:
    if root is None:
        try:
            from hermes_constants import get_hermes_home

            root = get_hermes_home()
        except Exception:
            root = Path.home() / ".hermes"
    plugin_dir = Path(root).expanduser() / "plugins" / "model-providers" / "antigravity"
    plugin_dir.mkdir(parents=True, exist_ok=True)
    (plugin_dir / "__init__.py").write_text(
        "import sys\n"
        "from pathlib import Path\n\n"
        "_src = Path(__file__).resolve().parents[2] / 'antigravity-provider' / 'src'\n"
        "if _src.is_dir() and str(_src) not in sys.path:\n"
        "    sys.path.insert(0, str(_src))\n\n"
        "from antigravity_provider.hermes_provider import register_provider_profile\n"
        "register_provider_profile()\n",
        encoding="utf-8",
    )
    (plugin_dir / "plugin.yaml").write_text(
        "name: antigravity\n"
        "kind: model-provider\n"
        "version: 0.2.0\n"
        "description: Google Antigravity provider profile\n",
        encoding="utf-8",
    )
    return plugin_dir
