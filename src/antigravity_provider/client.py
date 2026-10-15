"""HTTP transport for the Antigravity Cloud Code Assist endpoints."""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Any, Iterable, Iterator

from .cloudcode import antigravity_user_agent
from .errors import AntigravityError, TokenExpired
from .net import http_error_detail

ANTIGRAVITY_ENDPOINTS = [
    "https://daily-cloudcode-pa.googleapis.com",
    "https://daily-cloudcode-pa.sandbox.googleapis.com",
]
STREAM_PATH = "/v1internal:streamGenerateContent?alt=sse"
MODELS_PATH = "/v1internal:fetchAvailableModels"
# Statuses that may be specific to one endpoint, so the next endpoint is worth trying
# as long as nothing has been streamed yet.
RETRYABLE_ENDPOINT_STATUSES = {403, 404, 429, 500, 502, 503, 504}
STREAM_TIMEOUT_SECONDS = 300
MODELS_TIMEOUT_SECONDS = 15


def _sse_events(lines: Iterable[bytes]) -> Iterator[dict[str, Any]]:
    data_lines: list[str] = []

    def flush() -> Iterator[dict[str, Any]]:
        data = "\n".join(data_lines)
        data_lines.clear()
        if data and data != "[DONE]":
            yield json.loads(data)

    for raw in lines:
        line = raw.decode("utf-8", "replace").rstrip("\r\n")
        if not line:
            yield from flush()
        elif line.startswith("data:"):
            data_lines.append(line[5:].strip())
    yield from flush()


def _merge_model_catalogs(payloads: list[dict[str, Any]]) -> dict[str, Any]:
    """Union of several fetchAvailableModels payloads; earlier payloads win on scalar conflicts."""

    def merge(target: dict[str, Any], source: dict[str, Any]) -> None:
        for key, value in source.items():
            current = target.get(key)
            if isinstance(current, dict) and isinstance(value, dict):
                merge(current, value)
            elif isinstance(current, list) and isinstance(value, list):
                current.extend(item for item in value if item not in current)
            elif key not in target:
                target[key] = value

    merged: dict[str, Any] = {}
    for payload in payloads:
        merge(merged, payload)
    return merged


def _stream_event_error(event: dict[str, Any]) -> AntigravityError | None:
    error = event.get("error")
    if not error:
        return None
    error = error if isinstance(error, dict) else {"message": str(error)}
    code = int(error.get("code") or 500)
    if code == 401:
        return TokenExpired()
    return AntigravityError(error.get("message") or "Antigravity stream error", status=code)


class AntigravityClient:
    def __init__(self, *, endpoints: list[str] | None = None):
        self.endpoints = [endpoint.rstrip("/") for endpoint in (endpoints or ANTIGRAVITY_ENDPOINTS)]

    def _headers(self, access_token: str, accept: str) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json",
            "Accept": accept,
            "User-Agent": antigravity_user_agent(),
        }

    def stream_generate(self, *, access_token: str, body: dict[str, Any]) -> Iterator[dict[str, Any]]:
        """Yield upstream response chunks, trying the next endpoint only before the first chunk.

        Closing the returned generator closes the HTTP response.
        """
        payload = json.dumps(body).encode("utf-8")
        headers = self._headers(access_token, "text/event-stream")
        last_error: AntigravityError | None = None
        for endpoint in self.endpoints:
            emitted = False
            request = urllib.request.Request(endpoint + STREAM_PATH, data=payload, headers=headers, method="POST")
            try:
                with urllib.request.urlopen(request, timeout=STREAM_TIMEOUT_SECONDS) as response:
                    for event in _sse_events(response):
                        error = _stream_event_error(event)
                        if error is not None:
                            raise error
                        emitted = True
                        yield event["response"] if isinstance(event.get("response"), dict) else event
                if emitted:
                    return
                last_error = AntigravityError("Antigravity endpoint returned an empty stream", status=502)
            except TokenExpired:
                raise
            except AntigravityError as exc:
                if emitted or exc.status not in RETRYABLE_ENDPOINT_STATUSES:
                    raise
                last_error = exc
            except urllib.error.HTTPError as exc:
                if exc.code == 401:
                    exc.close()
                    raise TokenExpired() from exc
                last_error = AntigravityError(
                    f"Cloud Code Assist API error ({exc.code}): {http_error_detail(exc)}", status=exc.code
                )
                if exc.code not in RETRYABLE_ENDPOINT_STATUSES:
                    raise last_error from exc
            except (urllib.error.URLError, TimeoutError, OSError, ValueError) as exc:
                if emitted:
                    raise AntigravityError(f"Cloud Code Assist stream failed: {exc}", status=502) from exc
                last_error = AntigravityError(f"Cloud Code Assist connection failed: {exc}", status=502)
        raise last_error or AntigravityError("No Antigravity endpoint configured", status=502)

    def fetch_available_models(self, *, access_token: str, project_id: str) -> dict[str, Any]:
        """Merge the model catalogs every endpoint advertises for this account."""
        body = json.dumps({"project": project_id}).encode("utf-8")
        headers = self._headers(access_token, "application/json")
        payloads: list[dict[str, Any]] = []
        last_error: AntigravityError | None = None
        for endpoint in self.endpoints:
            request = urllib.request.Request(endpoint + MODELS_PATH, data=body, headers=headers, method="POST")
            try:
                with urllib.request.urlopen(request, timeout=MODELS_TIMEOUT_SECONDS) as response:
                    data = json.loads(response.read().decode("utf-8") or "{}")
                if isinstance(data, dict):
                    payloads.append(data)
            except urllib.error.HTTPError as exc:
                detail = http_error_detail(exc)
                last_error = (
                    TokenExpired()
                    if exc.code == 401
                    else AntigravityError(f"Cloud Code Assist API error ({exc.code}): {detail}", status=exc.code)
                )
            except (urllib.error.URLError, TimeoutError, OSError, ValueError) as exc:
                last_error = AntigravityError(f"Cloud Code Assist model discovery failed: {exc}", status=502)
        if not payloads:
            raise last_error or AntigravityError("Antigravity model discovery returned no response", status=502)
        return _merge_model_catalogs(payloads)
