"""Filesystem locations inside the active Hermes home."""

from __future__ import annotations

import os
from pathlib import Path

OAUTH_CREDENTIALS_FILE = ".antigravity_oauth.json"


def _legacy_hermes_home() -> Path:
    # Before 2026.10.15 the plugin ignored Hermes' platform defaults (e.g. %LOCALAPPDATA% on Windows).
    return Path(os.getenv("HERMES_HOME") or Path.home() / ".hermes").expanduser()


def hermes_home() -> Path:
    """Resolve the Hermes home the same way Hermes does, including profile overrides."""
    try:
        from hermes_constants import get_hermes_home

        return Path(get_hermes_home()).expanduser()
    except Exception:
        return _legacy_hermes_home()


def _uses_platform_default_home() -> bool:
    """True when Hermes chose its platform default rather than a profile or HERMES_HOME."""
    if os.getenv("HERMES_HOME", "").strip():
        return False
    try:
        from hermes_constants import get_hermes_home_override

        return not get_hermes_home_override()
    except Exception:
        return True


def oauth_credentials_path() -> Path:
    path = hermes_home() / OAUTH_CREDENTIALS_FILE
    legacy = _legacy_hermes_home() / OAUTH_CREDENTIALS_FILE
    # Before 2026.10.15 a login on e.g. Windows was saved under ~/.hermes instead of Hermes' platform
    # default. Keep using it, but never for a profile: that file belongs to the default profile.
    if not path.exists() and legacy != path and legacy.exists() and _uses_platform_default_home():
        return legacy
    return path


def model_cache_path() -> Path:
    return hermes_home() / ".antigravity_models.json"
