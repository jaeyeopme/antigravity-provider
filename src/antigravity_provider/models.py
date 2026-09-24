from __future__ import annotations

ANTIGRAVITY_PREFIX = "google-antigravity/"
DEFAULT_MODEL = "google-antigravity/gemini-3.8-flash"

KNOWN_MODELS: dict[str, int] = {
    "google-antigravity/gemini-3.8-flash": 65536,
    "google-antigravity/gemini-3.7-flash": 65536,
    "google-antigravity/gemini-3.6-flash": 65536,
    "google-antigravity/gemini-3.1-pro": 65535,
    "google-antigravity/claude-sonnet-4-6": 64000,
    "google-antigravity/claude-opus-4-6": 64000,
    "google-antigravity/gpt-oss-120b": 65536,
    "google-antigravity/gemini-3.5-flash": 65536,
}

MODEL_DISPLAY_NAMES: dict[str, str] = {
    "google-antigravity/gemini-3.8-flash": "Gemini 3.8 Flash",
    "google-antigravity/gemini-3.7-flash": "Gemini 3.7 Flash",
    "google-antigravity/gemini-3.6-flash": "Gemini 3.6 Flash",
    "google-antigravity/gemini-3.1-pro": "Gemini 3.1 Pro",
    "google-antigravity/claude-sonnet-4-6": "Claude Sonnet 4.6 (Thinking)",
    "google-antigravity/claude-opus-4-6": "Claude Opus 4.6 (Thinking)",
    "google-antigravity/gpt-oss-120b": "GPT-OSS 120B (Medium)",
    "google-antigravity/gemini-3.5-flash": "Gemini 3.5 Flash",
}

WIRE_PROFILES: dict[str, dict[str, object]] = {
    # Gemini 3.8 Flash
    "gemini-3.8-flash-high": {"wireModel": "gemini-3.8-flash-tiered", "modelEnum": "MODEL_PLACEHOLDER_M318", "maxOutputTokens": 65536},
    "gemini-3.8-flash-medium": {"wireModel": "gemini-3.8-flash-tiered", "modelEnum": "MODEL_PLACEHOLDER_M319", "maxOutputTokens": 65536},
    "gemini-3.8-flash-low": {"wireModel": "gemini-3.8-flash-tiered", "modelEnum": "MODEL_PLACEHOLDER_M320", "maxOutputTokens": 65536},
    # Gemini 3.7 Flash
    "gemini-3.7-flash-high": {"wireModel": "gemini-3.7-flash-tiered", "modelEnum": "MODEL_PLACEHOLDER_M298", "maxOutputTokens": 65536},
    "gemini-3.7-flash-medium": {"wireModel": "gemini-3.7-flash-tiered", "modelEnum": "MODEL_PLACEHOLDER_M299", "maxOutputTokens": 65536},
    "gemini-3.7-flash-low": {"wireModel": "gemini-3.7-flash-tiered", "modelEnum": "MODEL_PLACEHOLDER_M300", "maxOutputTokens": 65536},
    # Gemini 3.6 Flash
    "gemini-3.6-flash-high": {"wireModel": "gemini-3.6-flash-high", "modelEnum": "MODEL_PLACEHOLDER_M71", "maxOutputTokens": 65536},
    "gemini-3.6-flash-medium": {"wireModel": "gemini-3.6-flash-medium", "modelEnum": "MODEL_PLACEHOLDER_M72", "maxOutputTokens": 65536},
    "gemini-3.6-flash-low": {"wireModel": "gemini-3.6-flash-low", "modelEnum": "MODEL_PLACEHOLDER_M73", "maxOutputTokens": 65536},
    # Gemini 3.1 Pro
    "gemini-3.1-pro-low": {"modelEnum": "MODEL_PLACEHOLDER_M36", "maxOutputTokens": 65535},
    "gemini-pro-agent": {"modelEnum": "MODEL_PLACEHOLDER_M16", "maxOutputTokens": 65535},
    # Legacy Gemini 3.5 Flash
    "gemini-3.5-flash-extra-low": {"modelEnum": "MODEL_PLACEHOLDER_M187", "maxOutputTokens": 65536},
    "gemini-3.5-flash-low": {"modelEnum": "MODEL_PLACEHOLDER_M20", "maxOutputTokens": 65536},
    "gemini-3-flash-agent": {"modelEnum": "MODEL_PLACEHOLDER_M132", "maxOutputTokens": 65536},
    # Claude
    "claude-sonnet-4-6": {"maxOutputTokens": 64000},
    "claude-opus-4-6-thinking": {"maxOutputTokens": 64000},
    # GPT-OSS 120B
    "gpt-oss-120b-medium": {"modelEnum": "MODEL_OPENAI_GPT_OSS_120B_MEDIUM", "maxOutputTokens": 32768, "usedNonGeminiModel": True},
    # Aliases
    "gemini-3.8-flash-tiered": {"modelEnum": "MODEL_PLACEHOLDER_M318", "maxOutputTokens": 65536},
    "gemini-3.7-flash-tiered": {"modelEnum": "MODEL_PLACEHOLDER_M298", "maxOutputTokens": 65536},
    "openai/gpt-oss-120b-maas": {"wireModel": "gpt-oss-120b-medium", "modelEnum": "MODEL_OPENAI_GPT_OSS_120B_MEDIUM", "maxOutputTokens": 32768, "usedNonGeminiModel": True},
}


def strip_provider_prefix(model: str) -> str:
    model = (model or "").strip()
    return model[len(ANTIGRAVITY_PREFIX) :] if model.startswith(ANTIGRAVITY_PREFIX) else model


def normalize_model_id(model: str) -> str:
    model = (model or "").strip()
    if not model:
        return DEFAULT_MODEL
    if "/" not in model:
        return f"{ANTIGRAVITY_PREFIX}{model}"
    return model


def _effort(effort: str | None) -> str:
    value = (effort or "low").lower().replace("_", "-")
    if value in {"none", "off", "disabled"}:
        return "off"
    if value in {"minimum", "minimal"}:
        return "minimal"
    if value in {"medium", "normal"}:
        return "medium"
    if value in {"high", "xhigh", "max"}:
        return "high"
    return "low"


def clamp_reasoning_effort(model: str, reasoning_effort: str | None = None) -> str:
    logical = strip_provider_prefix(normalize_model_id(model))
    effort = _effort(reasoning_effort)
    if effort == "off":
        return "off"
    if logical == "gemini-3.1-pro":
        return "high" if effort == "high" else "low"
    if logical in {"gemini-3.8-flash", "gemini-3.7-flash", "gemini-3.6-flash", "gemini-3.5-flash"}:
        if effort == "high":
            return "high"
        if effort == "medium":
            return "medium"
        return "low"
    if logical in {"gpt-oss-120b", "gpt-oss-120b-medium", "openai/gpt-oss-120b-maas"}:
        return "medium"
    return effort


def resolve_wire_model_id(model: str, reasoning_effort: str | None = None) -> str:
    logical = strip_provider_prefix(normalize_model_id(model))
    effort = clamp_reasoning_effort(model, reasoning_effort)
    if logical == "gemini-3.8-flash":
        if effort == "high":
            return "gemini-3.8-flash-high"
        if effort == "medium":
            return "gemini-3.8-flash-medium"
        return "gemini-3.8-flash-low"
    if logical == "gemini-3.7-flash":
        if effort == "high":
            return "gemini-3.7-flash-high"
        if effort == "medium":
            return "gemini-3.7-flash-medium"
        return "gemini-3.7-flash-low"
    if logical == "gemini-3.6-flash":
        if effort == "high":
            return "gemini-3.6-flash-high"
        if effort == "medium":
            return "gemini-3.6-flash-medium"
        return "gemini-3.6-flash-low"
    if logical == "gemini-3.1-pro":
        return "gemini-pro-agent" if effort == "high" else "gemini-3.1-pro-low"
    if logical == "gemini-3.5-flash":
        if effort == "high":
            return "gemini-3-flash-agent"
        if effort == "medium":
            return "gemini-3.5-flash-low"
        return "gemini-3.5-flash-extra-low"
    if logical in {"claude-opus-4-6", "claude-opus-4-6-thinking"}:
        return "claude-opus-4-6-thinking"
    if logical == "claude-sonnet-4-6":
        return "claude-sonnet-4-6"
    if logical in {"gpt-oss-120b", "gpt-oss-120b-medium", "openai/gpt-oss-120b-maas"}:
        return "gpt-oss-120b-medium"
    return logical
