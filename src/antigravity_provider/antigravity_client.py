from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Any, Callable, Iterable

from .cloudcode import antigravity_user_agent
from .errors import ProxyError, TokenExpired

ANTIGRAVITY_ENDPOINTS = [
    "https://daily-cloudcode-pa.googleapis.com",
    "https://daily-cloudcode-pa.sandbox.googleapis.com",
]
STREAM_PATH = "/v1internal:streamGenerateContent?alt=sse"
MODELS_PATH = "/v1internal:fetchAvailableModels"
RETRYABLE_ENDPOINT_STATUSES = {403, 404, 429, 500, 502, 503, 504}

def _sse_json_lines(response: Iterable[bytes]) -> Iterable[dict[str, Any]]:
    data_lines: list[str] = []
    for raw in response:
        line = raw.decode("utf-8", "replace").rstrip("\r\n")
        if not line:
            if data_lines:
                data = "\n".join(data_lines)
                data_lines = []
                if data != "[DONE]":
                    yield json.loads(data)
            continue
        if line.startswith(":"):
            continue
        if line.startswith("data:"):
            data_lines.append(line[5:].strip())
    if data_lines:
        data = "\n".join(data_lines)
        if data != "[DONE]":
            yield json.loads(data)

def _merge_model_catalogs(payloads: list[dict[str, Any]]) -> dict[str, Any]:
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




class AntigravityClient:
    def __init__(
        self,
        *,
        endpoints: list[str] | None = None,
        post_json: Callable[[str, dict[str, Any], dict[str, str]], dict[str, Any]] | None = None,
    ):
        self.endpoints = [e.rstrip("/") for e in (endpoints or ANTIGRAVITY_ENDPOINTS)]
        self.post_json = post_json

    def _headers(self, access_token: str) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json",
            "Accept": "text/event-stream",
            "User-Agent": antigravity_user_agent(),
        }

    def stream_generate(self, *, access_token: str, body: dict[str, Any]) -> Iterable[dict[str, Any]]:
        payload = json.dumps(body).encode("utf-8")
        headers = self._headers(access_token)
        last_error: Exception | None = None
        for endpoint in self.endpoints:
            emitted = False
            req = urllib.request.Request(endpoint + STREAM_PATH, data=payload, headers=headers, method="POST")
            try:
                with urllib.request.urlopen(req, timeout=300) as resp:
                    for event in _sse_json_lines(resp):
                        if event.get("error"):
                            code = int(event.get("error", {}).get("code") or 500)
                            if code == 401:
                                raise TokenExpired()
                            raise ProxyError(event["error"].get("message") or "Antigravity stream error", status=code)
                        emitted = True
                        yield event.get("response") if isinstance(event.get("response"), dict) else event
                if emitted:
                    return
                last_error = ProxyError("Antigravity endpoint returned an empty stream", status=502)
            except TokenExpired:
                raise
            except ProxyError as exc:
                if emitted or exc.status not in RETRYABLE_ENDPOINT_STATUSES:
                    raise
                last_error = exc
            except urllib.error.HTTPError as exc:
                try:
                    detail = exc.read().decode("utf-8", "replace")
                finally:
                    exc.close()
                if exc.code == 401:
                    raise TokenExpired() from exc
                last_error = ProxyError(f"Cloud Code Assist API error ({exc.code}): {detail}", status=exc.code)
                if exc.code not in RETRYABLE_ENDPOINT_STATUSES:
                    raise last_error from exc
            except (urllib.error.URLError, ValueError) as exc:
                if emitted:
                    raise ProxyError(f"Cloud Code Assist stream failed: {exc}", status=502) from exc
                last_error = ProxyError(f"Cloud Code Assist connection failed: {exc}", status=502)
        if last_error:
            raise last_error
        raise ProxyError("No Antigravity endpoint configured", status=502)

    def fetch_available_models(self, *, access_token: str, project_id: str) -> dict[str, Any]:
        body = json.dumps({"project": project_id}).encode("utf-8")
        headers = {**self._headers(access_token), "Accept": "application/json"}
        payloads: list[dict[str, Any]] = []
        last_error: Exception | None = None
        for endpoint in self.endpoints:
            request = urllib.request.Request(endpoint + MODELS_PATH, data=body, headers=headers, method="POST")
            try:
                with urllib.request.urlopen(request, timeout=15) as response:
                    data = json.loads(response.read().decode("utf-8") or "{}")
                if isinstance(data, dict):
                    payloads.append(data)
            except urllib.error.HTTPError as exc:
                try:
                    detail = exc.read().decode("utf-8", "replace")
                finally:
                    exc.close()
                if exc.code == 401:
                    last_error = TokenExpired()
                else:
                    last_error = ProxyError(f"Cloud Code Assist API error ({exc.code}): {detail}", status=exc.code)
            except (urllib.error.URLError, ValueError) as exc:
                last_error = ProxyError(f"Cloud Code Assist model discovery failed: {exc}", status=502)
        if not payloads:
            if last_error:
                raise last_error
            raise ProxyError("Antigravity model discovery returned no response", status=502)
        return _merge_model_catalogs(payloads)

    def generate(self, *, access_token: str, body: dict[str, Any]) -> dict[str, Any]:
        if self.post_json is not None:
            return self.post_json(self.endpoints[0] + STREAM_PATH, body, self._headers(access_token))

        parts: list[dict[str, Any]] = []
        finish = "STOP"
        usage: dict[str, Any] = {}
        response_id: str | None = None
        saw_event = False
        for chunk in self.stream_generate(access_token=access_token, body=body):
            saw_event = True
            response_id = chunk.get("responseId") or response_id
            usage = chunk.get("usageMetadata") or usage
            candidate = (chunk.get("candidates") or [{}])[0]
            parts.extend(((candidate.get("content") or {}).get("parts") or []))
            finish = candidate.get("finishReason") or finish
        if not saw_event or (not parts and finish == "STOP"):
            raise ProxyError("Antigravity returned an empty stream", status=502)
        result: dict[str, Any] = {
            "candidates": [{"content": {"role": "model", "parts": parts}, "finishReason": finish}],
            "usageMetadata": usage,
        }
        if response_id:
            result["responseId"] = response_id
        return result
