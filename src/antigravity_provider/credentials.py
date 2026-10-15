"""Credential data, the per-profile browser OAuth store, and the macOS `agy` Keychain reader."""

from __future__ import annotations

import base64
import json
import subprocess
import sys
import time
from dataclasses import asdict, dataclass, replace
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

from .fileio import read_json, write_private_json
from .paths import oauth_credentials_path

SOURCE_BROWSER = "browser-oauth"
SOURCE_KEYCHAIN = "agy-keychain"
REFRESH_SKEW_SECONDS = 60


def _first_str(data: dict[str, Any], *keys: str) -> str:
    for key in keys:
        value = data.get(key)
        if isinstance(value, str) and value:
            return value
    return ""


def _epoch(value: object) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()
        except ValueError:
            return None
    return None


@dataclass(frozen=True)
class Credentials:
    access_token: str = ""
    refresh_token: str = ""
    expires_at: float | None = None
    project_id: str = ""
    email: str = ""
    token_type: str = "Bearer"
    source: str = ""

    @classmethod
    def from_mapping(cls, data: dict[str, Any], *, source: str) -> "Credentials":
        """Accept current and legacy key spellings in one place."""
        return cls(
            access_token=_first_str(data, "access_token", "access", "token"),
            refresh_token=_first_str(data, "refresh_token", "refresh"),
            expires_at=_epoch(data.get("expires_at", data.get("expires"))),
            project_id=_first_str(data, "project_id", "projectId"),
            email=_first_str(data, "email"),
            token_type=_first_str(data, "token_type") or "Bearer",
            source=source,
        )

    def to_mapping(self) -> dict[str, Any]:
        data = asdict(self)
        data.pop("source")
        return {key: value for key, value in data.items() if value not in ("", None)}

    @property
    def usable(self) -> bool:
        return bool(self.access_token or self.refresh_token)

    def needs_refresh(self, now: float | None = None) -> bool:
        if not self.refresh_token:
            return False
        if not self.access_token:
            return True
        if self.expires_at is None:
            return False
        return (now if now is not None else time.time()) + REFRESH_SKEW_SECONDS >= self.expires_at

    def with_tokens(self, tokens: dict[str, Any]) -> "Credentials":
        return replace(
            self,
            access_token=str(tokens["access_token"]),
            refresh_token=str(tokens.get("refresh_token") or self.refresh_token),
            expires_at=_epoch(tokens.get("expires_at")),
            token_type=str(tokens.get("token_type") or self.token_type),
        )


class CredentialStore:
    """Browser OAuth credentials saved in the active Hermes profile."""

    def __init__(self, path: Path):
        self.path = Path(path).expanduser()

    @classmethod
    def default(cls) -> "CredentialStore":
        return cls(oauth_credentials_path())

    def load(self) -> Credentials | None:
        data = read_json(self.path)
        if not isinstance(data, dict):
            return None
        credentials = Credentials.from_mapping(data, source=SOURCE_BROWSER)
        return credentials if credentials.usable else None

    def save(self, credentials: Credentials) -> None:
        write_private_json(self.path, credentials.to_mapping())

    def delete(self) -> None:
        try:
            self.path.unlink()
        except FileNotFoundError:
            pass


def parse_agy_keychain_secret(raw: str) -> Credentials | None:
    raw = raw.strip()
    if raw.startswith("go-keyring-base64:"):
        raw = base64.b64decode(raw.split(":", 1)[1]).decode("utf-8")
    data = json.loads(raw)
    token = data.get("token") if isinstance(data, dict) else None
    if not isinstance(token, dict) or not token.get("access_token"):
        return None
    return Credentials.from_mapping(
        {
            "access_token": token.get("access_token"),
            "refresh_token": token.get("refresh_token"),
            "expires_at": token.get("expiry"),
            "token_type": token.get("token_type"),
        },
        source=SOURCE_KEYCHAIN,
    )


def _read_keychain_secret() -> str:
    return subprocess.check_output(
        ["security", "find-generic-password", "-a", "antigravity", "-s", "gemini", "-w"],
        stderr=subprocess.DEVNULL,
        timeout=5,
    ).decode("utf-8")


def load_agy_keychain_credentials(*, runner: Callable[[], str] | None = None) -> Credentials | None:
    """Read the credential the `agy` CLI keeps in the macOS Keychain, if any."""
    if runner is None:
        if sys.platform != "darwin":
            return None
        runner = _read_keychain_secret
    try:
        return parse_agy_keychain_secret(runner())
    except Exception:
        return None
