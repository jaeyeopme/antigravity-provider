from __future__ import annotations

ANTIGRAVITY_PREFIX = "google-antigravity/"


def strip_provider_prefix(model: str) -> str:
    model = (model or "").strip()
    return model[len(ANTIGRAVITY_PREFIX) :] if model.startswith(ANTIGRAVITY_PREFIX) else model


def normalize_model_id(model: str) -> str:
    model = (model or "").strip()
    if model and "/" not in model:
        return f"{ANTIGRAVITY_PREFIX}{model}"
    return model


def normalize_effort(effort: str | None) -> str:
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
