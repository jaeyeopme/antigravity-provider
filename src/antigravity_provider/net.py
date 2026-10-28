"""Small urllib helpers shared by OAuth, project discovery, and the Cloud Code client."""

from __future__ import annotations

import http.client
import json
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

from .errors import AntigravityError


def http_error_detail(error: urllib.error.HTTPError) -> str:
    try:
        return error.read().decode("utf-8", "replace")
    finally:
        error.close()


def request_json(
    url: str,
    *,
    headers: dict[str, str],
    json_body: Any = None,
    form: dict[str, str] | None = None,
    timeout: float = 60,
    error_prefix: str = "Request failed",
) -> dict[str, Any]:
    """POST JSON or form data (GET when neither is given) and decode a JSON object response."""
    data: bytes | None = None
    if form is not None:
        data = urllib.parse.urlencode(form).encode("utf-8")
        headers = {"Content-Type": "application/x-www-form-urlencoded", **headers}
    elif json_body is not None:
        data = json.dumps(json_body).encode("utf-8")
        headers = {"Content-Type": "application/json", **headers}
    request = urllib.request.Request(
        url, data=data, headers=headers, method="POST" if data is not None else "GET"
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            payload = json.loads(response.read().decode("utf-8") or "{}")
    except urllib.error.HTTPError as exc:
        raise AntigravityError(
            f"{error_prefix} ({exc.code}): {http_error_detail(exc)}", status=exc.code
        ) from exc
    except (OSError, http.client.HTTPException, ValueError) as exc:
        raise AntigravityError(f"{error_prefix}: {exc}", status=502) from exc
    return payload if isinstance(payload, dict) else {}
