"""Cloud Code Assist identity: client User-Agent and project discovery/onboarding."""

from __future__ import annotations

import http.client
import os
import platform
import re
import time
import urllib.error
import urllib.request
from collections.abc import Callable
from pathlib import Path
from typing import Any

from .errors import AntigravityError
from .fileio import read_json, write_private_json
from .net import request_json
from .paths import client_version_path

CLOUD_CODE_ENDPOINT = "https://cloudcode-pa.googleapis.com"
ANTIGRAVITY_LOAD_CODE_ASSIST_METADATA = {
    "ideType": "ANTIGRAVITY",
    "platform": "PLATFORM_UNSPECIFIED",
    "pluginType": "GEMINI",
}
# The update manifest the Antigravity IDE's own updater reads. Only the macOS one has a known
# address; its version is presented on every platform, as oh-my-pi does.
CLIENT_VERSION_URL = (
    "https://antigravity-hub-auto-updater-974169037036.us-central1.run.app"
    "/manifest/latest-arm64-mac.yml"
)
CLIENT_VERSION_TIMEOUT_SECONDS = 5
# Presented when the update server cannot be read and no earlier process saved a newer version.
# A weekly CI job (.github/workflows/client-version.yml, scripts/check_client_version.py) fails
# when the update server cannot be read, or when this version is more than
# CLIENT_VERSION_MAX_AGE_DAYS old and a newer one is out; then raise both lines below.
DEFAULT_CLIENT_VERSION = "2.34.0"
DEFAULT_CLIENT_VERSION_SET = "2026-11-24"
CLIENT_VERSION_MAX_AGE_DAYS = 30
_VERSION = r"\d+\.\d+\.\d+"
TIER_LEGACY = "legacy-tier"
PROJECT_ONBOARD_MAX_ATTEMPTS = 5
PROJECT_ONBOARD_INTERVAL_SECONDS = 2

PostJson = Callable[[str, dict[str, Any], dict[str, str]], dict[str, Any]]


def fetch_released_version() -> str:
    """The Antigravity version its update server ships now."""
    try:
        request = urllib.request.Request(
            CLIENT_VERSION_URL,
            # What the IDE's updater sends.
            headers={"Cache-Control": "no-cache", "User-Agent": "electron-builder"},
        )
        with urllib.request.urlopen(request, timeout=CLIENT_VERSION_TIMEOUT_SECONDS) as response:
            manifest = response.read(4096).decode("utf-8", "replace")
    except (OSError, http.client.HTTPException) as exc:
        if isinstance(exc, urllib.error.HTTPError):
            exc.close()
        raise AntigravityError(f"{CLIENT_VERSION_URL}: {exc}", status=502) from exc
    version = re.search(rf"""^version: *["']?({_VERSION})["']?\s*$""", manifest, re.M)
    if version is None:
        raise AntigravityError(f"{CLIENT_VERSION_URL} names no version", status=502)
    return version.group(1)


def _release(version: str) -> tuple[int, ...]:
    """A version as numbers, so that 2.9.0 sorts before 2.30.0."""
    return tuple(int(part) for part in version.split("."))


class ClientVersion:
    """The Antigravity version presented to the backend, as its update server reports it.

    Asked once per process, on the first request, as oh-my-pi does. When the update server cannot
    be read, the newer of the version an earlier process saved and DEFAULT_CLIENT_VERSION is used
    for the rest of this one.
    """

    def __init__(
        self,
        *,
        fetch: Callable[[], str] = fetch_released_version,
        path: Path | Callable[[], Path] = client_version_path,
    ) -> None:
        self._fetch = fetch
        self._path = path
        self._version: str | None = None

    def get(self) -> str:
        if self._version is None:
            path = self._path() if callable(self._path) else self._path
            try:
                self._version = self._fetch()
            except AntigravityError:
                saved = read_json(path)
                saved = saved.get("version") if isinstance(saved, dict) else None
                version = DEFAULT_CLIENT_VERSION
                # A hand-edited or damaged file must not put arbitrary text into a header.
                if isinstance(saved, str) and re.fullmatch(_VERSION, saved):
                    # A plugin release may have raised the built-in version past the saved one.
                    version = max(saved, version, key=_release)
                self._version = version
            else:
                try:
                    write_private_json(path, {"version": self._version})
                except OSError:
                    pass  # e.g. a read-only home; the version still works from memory
        return self._version


client_version = ClientVersion()


def antigravity_user_agent() -> str:
    """The User-Agent of the Antigravity IDE, in the form oh-my-pi captured from the real client.

    Why `hub` (the IDE) and not `cli` (what `agy` sends, `antigravity/cli/<agy version>`), as
    measured against the backend with one account in November 2026:
    - Both get the same answers: with current versions (`hub/2.34.0`, `cli/1.5.15`) the model
      list, default model and project lookup were identical. Nothing is gained by switching.
    - `hub` tolerates an old version far longer. `hub/2.1.4`, five months old, was still served;
      `cli/1.0.0`, about six months old, was refused with a "no longer supported" text that
      arrives as if it were the model's answer. `agy` releases every day or two.
    - oh-my-pi, the implementation this plugin follows, calls the backend directly as `hub`; it
      only uses `cli` by running the real `agy`. Nobody else calls the backend directly as `cli`.
    The version must then be the IDE's, from its updater (CLIENT_VERSION_URL); `agy`'s version
    under `hub` reads as an ancient IDE (`hub/1.5.15` got 15 models instead of 22).
    """
    version = (
        os.getenv("ANTIGRAVITY_CLIENT_VERSION")
        or os.getenv("PI_AI_ANTIGRAVITY_VERSION")  # legacy name, kept for existing setups
        or client_version.get()
    )
    # One build per OS is named whatever the host is; what the darwin-x64 build sends is not known.
    system = platform.system().lower()
    if system == "darwin":
        os_name, arch = "darwin", "arm64"
    elif system.startswith("win"):
        os_name, arch = "windows", "amd64"
    else:
        os_name, arch = "linux", "amd64"
    # The backend does not check cl (oh-my-pi verified); the update manifest carries none.
    return (
        f"antigravity/hub/{version} (aidev_client; os_type={os_name}; arch={arch}; cl=1005016104)"
    )


def _post_json(url: str, body: dict[str, Any], headers: dict[str, str]) -> dict[str, Any]:
    return request_json(
        url,
        headers=headers,
        json_body=body,
        timeout=120,
        error_prefix="Cloud Code Assist API error",
    )


def read_project_id(value: object) -> str | None:
    if isinstance(value, str) and value:
        return value
    if isinstance(value, dict) and isinstance(value.get("id"), str) and value["id"]:
        return value["id"]
    return None


def read_default_tier(allowed_tiers: object) -> str:
    if not isinstance(allowed_tiers, list):
        return TIER_LEGACY
    for tier in allowed_tiers:
        if (
            isinstance(tier, dict)
            and tier.get("isDefault")
            and isinstance(tier.get("id"), str)
            and tier["id"]
        ):
            return tier["id"]
    return TIER_LEGACY


def load_or_onboard_project(
    access_token: str,
    *,
    post_json: PostJson | None = None,
    sleep: Callable[[float], None] = time.sleep,
) -> str:
    post_json = post_json or _post_json
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json",
        "User-Agent": antigravity_user_agent(),
    }
    load_payload = post_json(
        f"{CLOUD_CODE_ENDPOINT}/v1internal:loadCodeAssist",
        {"metadata": ANTIGRAVITY_LOAD_CODE_ASSIST_METADATA},
        headers,
    )
    existing = read_project_id(load_payload.get("cloudaicompanionProject"))
    if existing:
        return existing

    onboard_body = {
        "tierId": read_default_tier(load_payload.get("allowedTiers")),
        "metadata": ANTIGRAVITY_LOAD_CODE_ASSIST_METADATA,
    }
    for attempt in range(1, PROJECT_ONBOARD_MAX_ATTEMPTS + 1):
        if attempt > 1:
            sleep(PROJECT_ONBOARD_INTERVAL_SECONDS)
        op = post_json(f"{CLOUD_CODE_ENDPOINT}/v1internal:onboardUser", onboard_body, headers)
        if not op.get("done"):
            continue
        project_id = read_project_id((op.get("response") or {}).get("cloudaicompanionProject"))
        if project_id:
            return project_id
    raise AntigravityError("onboardUser did not return a project id", status=502)
