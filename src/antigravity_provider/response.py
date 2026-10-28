"""Cloud Code Assist response chunks → OpenAI chat-completion objects and stream chunks."""

from __future__ import annotations

import json
import time
import uuid
from collections.abc import Iterable, Iterator
from typing import Any

from .errors import AntigravityError
from .models import normalize_model_id

_CONTENT_FILTER_REASONS = {"SAFETY", "PROHIBITED_CONTENT", "BLOCKLIST", "SPII", "RECITATION"}
# The model tried to call a tool and failed. With nothing else produced, surface it as a retryable
# provider error instead of an empty assistant message.
_FAILED_TOOL_CALL_REASONS = {"MALFORMED_FUNCTION_CALL", "UNEXPECTED_TOOL_CALL"}


def _candidate(response: dict[str, Any]) -> dict[str, Any]:
    candidates = response.get("candidates") or []
    candidate = candidates[0] if candidates else {}
    return candidate if isinstance(candidate, dict) else {}


def _parts(candidate: dict[str, Any]) -> list[dict[str, Any]]:
    parts = (candidate.get("content") or {}).get("parts") or []
    return [part for part in parts if isinstance(part, dict)]


def _finish_reason(reason: str | None) -> str:
    if reason == "MAX_TOKENS":
        return "length"
    if reason in _CONTENT_FILTER_REASONS:
        return "content_filter"
    return "stop"


def _failed_tool_call(reason: str | None) -> AntigravityError:
    return AntigravityError(f"Antigravity model ended the turn with {reason}", status=502)


def _empty_stream(saw_part: bool, finish: str | None) -> AntigravityError | None:
    """A turn with no output is a retryable provider error, not an empty reply."""
    if not saw_part and finish in (None, "STOP"):
        return AntigravityError("Antigravity returned an empty stream", status=502)
    return None


def _usage(response: dict[str, Any]) -> dict[str, int]:
    usage = response.get("usageMetadata") or {}
    prompt = int(usage.get("promptTokenCount") or 0)
    completion = int(usage.get("candidatesTokenCount") or 0) + int(
        usage.get("thoughtsTokenCount") or 0
    )
    total = int(usage.get("totalTokenCount") or prompt + completion)
    return {"prompt_tokens": prompt, "completion_tokens": completion, "total_tokens": total}


def _tool_call(part: dict[str, Any]) -> dict[str, Any]:
    call = part.get("functionCall") or {}
    args = call.get("args") if isinstance(call.get("args"), dict) else {}
    tool_call: dict[str, Any] = {
        "id": call.get("id") or f"call_{uuid.uuid4().hex[:24]}",
        "type": "function",
        "function": {
            "name": call.get("name") or "tool",
            "arguments": json.dumps(args, separators=(",", ":"), ensure_ascii=False),
        },
    }
    signature = part.get("thoughtSignature")
    if isinstance(signature, str) and signature:
        # Hermes stores this on the tool call and replays it with the history (see request.py).
        tool_call["extra_content"] = {"google": {"thought_signature": signature}}
    return tool_call


def collect_response(chunks: Iterable[dict[str, Any]]) -> dict[str, Any]:
    """Fold streamed chunks into one response, as the non-streaming API would return it."""
    parts: list[dict[str, Any]] = []
    finish: str | None = None
    usage: dict[str, Any] = {}
    response_id: str | None = None
    for chunk in chunks:
        response_id = chunk.get("responseId") or response_id
        usage = chunk.get("usageMetadata") or usage
        candidate = _candidate(chunk)
        parts.extend(_parts(candidate))
        finish = candidate.get("finishReason") or finish
    error = _empty_stream(bool(parts), finish)
    if error is not None:
        raise error
    # Model events carry a responseId; a backend notice (e.g. a retired model) has none and no finishReason.
    if finish is None and response_id:
        raise AntigravityError("Antigravity stream ended without a finish reason", status=502)
    response: dict[str, Any] = {
        "candidates": [
            {"content": {"role": "model", "parts": parts}, "finishReason": finish or "STOP"}
        ],
        "usageMetadata": usage,
    }
    if response_id:
        response["responseId"] = response_id
    return response


def to_openai_completion(model: str, response: dict[str, Any]) -> dict[str, Any]:
    candidate = _candidate(response)
    text: list[str] = []
    reasoning: list[str] = []
    tool_calls: list[dict[str, Any]] = []
    for part in _parts(candidate):
        if "functionCall" in part:
            tool_calls.append(_tool_call(part))
        elif isinstance(part.get("text"), str):
            (reasoning if part.get("thought") else text).append(part["text"])

    reason = candidate.get("finishReason")
    if reason in _FAILED_TOOL_CALL_REASONS and not text and not tool_calls:
        raise _failed_tool_call(reason)

    message: dict[str, Any] = {"role": "assistant", "content": "".join(text) if text else None}
    if reasoning:
        message["reasoning_content"] = "".join(reasoning)
    if tool_calls:
        message["tool_calls"] = tool_calls
    return {
        "id": "chatcmpl-" + uuid.uuid4().hex,
        "object": "chat.completion",
        "created": int(time.time()),
        "model": normalize_model_id(model),
        "choices": [
            {
                "index": 0,
                "message": message,
                "finish_reason": "tool_calls" if tool_calls else _finish_reason(reason),
            }
        ],
        "usage": _usage(response),
    }


def to_openai_stream_chunks(
    model: str, events: Iterable[dict[str, Any]]
) -> Iterator[dict[str, Any]]:
    completion_id = "chatcmpl-" + uuid.uuid4().hex
    created = int(time.time())
    public_model = normalize_model_id(model)
    tool_index = 0
    produced_output = False
    saw_part = False
    model_turn = False
    finish: str | None = None
    usage: dict[str, int] | None = None

    def chunk(
        delta: dict[str, Any], finish_reason: str | None = None, usage: dict[str, int] | None = None
    ) -> dict[str, Any]:
        value: dict[str, Any] = {
            "id": completion_id,
            "object": "chat.completion.chunk",
            "created": created,
            "model": public_model,
            "choices": [{"index": 0, "delta": delta, "finish_reason": finish_reason}],
        }
        if usage is not None:
            value["usage"] = usage
        return value

    for event in events:
        model_turn = model_turn or bool(event.get("responseId"))
        candidate = _candidate(event)
        for part in _parts(candidate):
            saw_part = True
            if "functionCall" in part:
                yield chunk({"tool_calls": [{"index": tool_index, **_tool_call(part)}]})
                tool_index += 1
                produced_output = True
            elif isinstance(part.get("text"), str):
                if part.get("thought"):
                    yield chunk({"reasoning_content": part["text"]})
                else:
                    yield chunk({"content": part["text"]})
                    produced_output = True

        if event.get("usageMetadata"):
            usage = _usage(event)  # may arrive in its own event after the finish reason
        reason = candidate.get("finishReason")
        if reason:
            if reason in _FAILED_TOOL_CALL_REASONS and not produced_output:
                raise _failed_tool_call(reason)
            finish = reason

    error = _empty_stream(saw_part, finish)
    if error is not None:
        raise error
    # A stream without a responseId is a backend notice (e.g. a retired model): the whole reply.
    if finish is None and model_turn:
        return  # cut off: without a finish_reason Hermes requests a continuation
    yield chunk({}, "tool_calls" if tool_index else _finish_reason(finish), usage)
