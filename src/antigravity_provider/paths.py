"""Filesystem locations inside the active Hermes home."""

from __future__ import annotations

import os
from pathlib import Path


OAUTH_CREDENTIALS_FILE = ".antigravity_oauth.json"


def _legacy_hermes_home() -> Path:
    # Before 0.3.0 the plugin ignored Hermes' platform defaults (e.g. %LOCALAPPDATA% on Windows).
    return Path(os.getenv("HERMES_HOME") or Path.home() / ".hermes").expanduser()


def hermes_home() -> Path:
    """Resolve the Hermes home the same way Hermes does, including profile overrides."""
    try:
        from hermes_constants import get_hermes_home

        return Path(get_hermes_home()).expanduser()
    except Exception:
        return _legacy_hermes_home()


def oauth_credentials_path() -> Path:
    path = hermes_home() / OAUTH_CREDENTIALS_FILE
    legacy = _legacy_hermes_home() / OAUTH_CREDENTIALS_FILE
    # Keep using a login saved by an earlier version rather than silently dropping it.
    if not path.exists() and legacy != path and legacy.exists():
        return legacy
    return path


def model_cache_path() -> Path:
    return hermes_home() / ".antigravity_models.json"
