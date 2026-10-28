"""OpenAI chat-completions request → Cloud Code Assist ``streamGenerateContent`` body."""

from __future__ import annotations

import hashlib
import json
import secrets
import time
import uuid
from dataclasses import dataclass, field
from typing import Any

from .catalog import ModelCatalog, ResolvedRoute, fallback_catalog
from .models import normalize_effort, normalize_model_id
from .schema import to_gemini_schema

# Gemini 3 rejects replayed functionCall parts without a thought signature. When history has no
# real signature (other provider, or a session from before 2026.10.15), this documented placeholder
# is sent instead.
SKIP_THOUGHT_SIGNATURE = "skip_thought_signature_validator"


@dataclass
class ChatRequest:
    model: str
    messages: list[dict[str, Any]]
    tools: list[dict[str, Any]] = field(default_factory=list)
    tool_choice: Any = None
    reasoning_effort: str | None = None
    max_tokens: int | None = None
    temperature: float | None = None
    top_p: float | None = None


def _is_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _number(value: Any) -> float | None:
    return value if isinstance(value, (int, float)) and not isinstance(value, bool) else None


def parse_chat_request(payload: dict[str, Any]) -> ChatRequest:
    if not isinstance(payload, dict):
        raise ValueError("request body must be a JSON object")
    messages = payload.get("messages")
    if not isinstance(messages, list):
        raise ValueError("messages must be a list")
    if any(not isinstance(message, dict) for message in messages):
        raise ValueError("messages entries must be JSON objects")
    reasoning = payload.get("reasoning_effort")
    if reasoning is None and isinstance(payload.get("reasoning"), dict):
        reasoning = payload["reasoning"].get("effort")
    if reasoning is None and isinstance(payload.get("extra_body"), dict):
        extra_reasoning = payload["extra_body"].get("reasoning")
        if isinstance(extra_reasoning, dict):
            reasoning = extra_reasoning.get("effort")
    max_tokens = payload.get("max_tokens")
    if not _is_int(max_tokens):
        max_tokens = payload.get("max_completion_tokens")
    return ChatRequest(
        model=normalize_model_id(str(payload.get("model") or "")),
        messages=messages,
        tools=payload.get("tools") if isinstance(payload.get("tools"), list) else [],
        tool_choice=payload.get("tool_choice"),
        reasoning_effort=str(reasoning) if reasoning is not None else None,
        max_tokens=max_tokens if _is_int(max_tokens) else None,
        temperature=_number(payload.get("temperature")),
        top_p=_number(payload.get("top_p")),
    )


def _content_text(content: Any) -> str:
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        texts: list[str] = []
        for item in content:
            if isinstance(item, dict):
                if item.get("type") == "text" and isinstance(item.get("text"), str):
                    texts.append(item["text"])
                elif item.get("type") == "image_url":
                    texts.append("[image omitted]")
        return "\n".join(text for text in texts if text)
    return str(content)


def _parts_from_content(content: Any) -> list[dict[str, Any]]:
    if not isinstance(content, list):
        text = _content_text(content)
        return [{"text": text}] if text.strip() else []
    parts: list[dict[str, Any]] = []
    for item in content:
        if not isinstance(item, dict):
            continue
        if item.get("type") == "text" and isinstance(item.get("text"), str) and item["text"].strip():
            parts.append({"text": item["text"]})
        elif item.get("type") == "image_url":
            image = item.get("image_url")
            url = image.get("url") if isinstance(image, dict) else None
            if isinstance(url, str) and url.startswith("data:") and ";base64," in url:
                meta, data = url.split(",", 1)
                mime = meta[5:].split(";", 1)[0] or "application/octet-stream"
                parts.append({"inlineData": {"mimeType": mime, "data": data}})
            else:
                parts.append({"text": "[image omitted]"})
    return parts


def _parse_args(raw: Any) -> dict[str, Any]:
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str) and raw.strip():
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            return {"value": raw}
        return parsed if isinstance(parsed, dict) else {"value": parsed}
    return {}


def thought_signature(tool_call: dict[str, Any]) -> str | None:
    """Signature Hermes replays in ``extra_content`` (``google.thought_signature`` or flat)."""
    extra = tool_call.get("extra_content")
    if not isinstance(extra, dict):
        return None
    google = extra.get("google")
    signature = google.get("thought_signature") if isinstance(google, dict) else extra.get("thought_signature")
    return signature if isinstance(signature, str) and signature.strip() else None


def _requires_thought_signature(wire_model: str) -> bool:
    return wire_model.startswith(("gemini-3", "gemini-pro"))


def _accepts_thought_signature(wire_model: str) -> bool:
    # Signatures are issued by Gemini; a conversation switched to Claude or gpt-oss must not
    # replay them.
    return wire_model.startswith("gemini")


def _model_parts(message: dict[str, Any], wire_model: str, call_names: dict[str, str]) -> list[dict[str, Any]]:
    parts = _parts_from_content(message.get("content"))
    calls: list[tuple[dict[str, Any], str | None]] = []
    for tool_call in message.get("tool_calls") or []:
        if not isinstance(tool_call, dict):
            continue
        fn = tool_call.get("function")
        name = fn.get("name") if isinstance(fn, dict) else None
        if not name:
            continue
        part = {"functionCall": {"name": name, "args": _parse_args(fn.get("arguments"))}}
        if tool_call.get("id"):
            call_names[str(tool_call["id"])] = name
            # Claude and gpt-oss routes reject replayed tool calls and results without their id.
            part["functionCall"]["id"] = str(tool_call["id"])
        calls.append((part, thought_signature(tool_call)))

    if not _accepts_thought_signature(wire_model):
        calls = [(part, None) for part, _ in calls]
    has_real_signature = any(signature for _, signature in calls)
    for part, signature in calls:
        if signature:
            part["thoughtSignature"] = signature
        elif not has_real_signature and _requires_thought_signature(wire_model):
            part["thoughtSignature"] = SKIP_THOUGHT_SIGNATURE
        parts.append(part)
    return parts


def _function_declarations(tools: list[dict[str, Any]]) -> list[dict[str, Any]] | None:
    declarations = []
    for tool in tools or []:
        if not isinstance(tool, dict) or tool.get("type") != "function":
            continue
        fn = tool.get("function") or {}
        if not isinstance(fn, dict) or not fn.get("name"):
            continue
        parameters = to_gemini_schema(fn.get("parameters"))
        declarations.append({"name": fn["name"], "description": fn.get("description") or "", "parameters": parameters})
    return [{"functionDeclarations": declarations}] if declarations else None


def _tool_config(tools: list[dict[str, Any]], tool_choice: Any, wire_model: str) -> dict[str, Any] | None:
    if isinstance(tool_choice, str):
        choice = tool_choice.lower()
        if choice == "none":
            return {"functionCallingConfig": {"mode": "NONE"}}
        if choice in {"required", "any"}:
            return {"functionCallingConfig": {"mode": "ANY"}}
    if isinstance(tool_choice, dict):
        fn = tool_choice.get("function") if tool_choice.get("type") == "function" else None
        name = fn.get("name") if isinstance(fn, dict) else None
        if name:
            return {"functionCallingConfig": {"mode": "ANY", "allowedFunctionNames": [name]}}
    if tools or wire_model.startswith("claude-"):
        return {"functionCallingConfig": {"mode": "VALIDATED"}}
    return None


def _session_id(messages: list[dict[str, Any]], session_id: str | None = None) -> str:
    """Stable per conversation: the Hermes session id, else the first user message."""
    identity = session_id
    if not identity:
        for message in messages:
            if message.get("role") == "user":
                text = _content_text(message.get("content"))
                if text.strip():
                    identity = text
                    break
    if identity:
        digest = hashlib.sha256(identity.encode("utf-8")).digest()[:8]
        return "-" + str(int.from_bytes(digest, "big") & ((1 << 63) - 1))
    return "-" + str(secrets.randbelow(9_000_000_000_000_000_000))


def _envelope_labels(route: ResolvedRoute, step: int = 2) -> dict[str, str]:
    used_claude = route.wire_model.startswith("claude-")
    labels = {
        "last_step_index": str(step - 1),
        "trajectory_id": str(uuid.uuid4()),
        "used_claude": str(used_claude).lower(),
        "used_claude_conservative": str(used_claude).lower(),
        "used_non_gemini_model": str(route.used_non_gemini_model).lower(),
    }
    if route.model_enum:
        labels["model_enum"] = route.model_enum
    return labels


def _contents(messages: list[dict[str, Any]], wire_model: str) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
    system_parts: list[dict[str, str]] = []
    contents: list[dict[str, Any]] = []
    call_names: dict[str, str] = {}
    for message in messages:
        role = message.get("role")
        if role in {"system", "developer"}:
            text = _content_text(message.get("content"))
            if text.strip():
                system_parts.append({"text": text})
        elif role == "user":
            parts = _parts_from_content(message.get("content"))
            if parts:
                contents.append({"role": "user", "parts": parts})
        elif role == "assistant":
            parts = _model_parts(message, wire_model, call_names)
            if parts:
                contents.append({"role": "model", "parts": parts})
        elif role == "tool":
            name = message.get("name") or call_names.get(str(message.get("tool_call_id") or "")) or "tool"
            content = message.get("content")
            result_parts = _parts_from_content(content) if isinstance(content, list) else []
            output = "\n".join(p["text"] for p in result_parts if "text" in p) if result_parts else _content_text(content)
            part = {"functionResponse": {"name": name, "response": {"output": output}}}
            images = [p for p in result_parts if "inlineData" in p]
            if images:
                # Gemini and Claude routes read images here; beside the response, gpt-oss routes fail.
                part["functionResponse"]["parts"] = images
            if message.get("tool_call_id"):
                part["functionResponse"]["id"] = str(message["tool_call_id"])
            previous = contents[-1] if contents else None
            # Results of one parallel tool batch go back together in a single user turn.
            if previous and previous["role"] == "user" and any("functionResponse" in p for p in previous["parts"]):
                previous["parts"].append(part)
            else:
                contents.append({"role": "user", "parts": [part]})
    if not contents:
        contents.append({"role": "user", "parts": [{"text": "Continue."}]})
    return contents, system_parts


def build_generate_content_request(
    request: ChatRequest,
    *,
    project_id: str,
    session_id: str | None = None,
    catalog: ModelCatalog | None = None,
) -> dict[str, Any]:
    route = (catalog or fallback_catalog()).resolve(request.model, normalize_effort(request.reasoning_effort))
    contents, system_parts = _contents(request.messages, route.wire_model)

    max_tokens = request.max_tokens
    max_output = (
        min(max_tokens, route.max_output_tokens)
        if isinstance(max_tokens, int) and max_tokens > 0
        else route.max_output_tokens
    )
    budget = route.thinking_budget
    if route.wire_model.startswith("claude-") and budget is not None and 0 < budget and max_output <= budget:
        # Claude counts thinking toward max_tokens and rejects max_tokens <= the thinking budget.
        max_output = min(budget + max_output, route.max_output_tokens)
    generation_config: dict[str, Any] = {"maxOutputTokens": max_output}
    if route.thinking_budget is not None:
        generation_config["thinkingConfig"] = {
            "includeThoughts": route.include_thoughts,
            "thinkingBudget": route.thinking_budget,
        }
    if request.temperature is not None:
        generation_config["temperature"] = request.temperature
    if request.top_p is not None:
        generation_config["topP"] = request.top_p

    upstream: dict[str, Any] = {
        "contents": contents,
        "generationConfig": generation_config,
        "sessionId": _session_id(request.messages, session_id),
        "labels": _envelope_labels(route),
    }
    if system_parts:
        upstream["systemInstruction"] = {"role": "system", "parts": system_parts}
    declarations = _function_declarations(request.tools)
    if declarations:
        upstream["tools"] = declarations
    tool_config = _tool_config(request.tools, request.tool_choice, route.wire_model)
    if tool_config:
        upstream["toolConfig"] = tool_config

    return {
        "project": project_id,
        "model": route.wire_model,
        "request": upstream,
        "requestType": "agent",
        "userAgent": "antigravity",
        "requestId": f"agent/{uuid.uuid4()}/{int(time.time() * 1000)}/{uuid.uuid4()}/2",
    }
