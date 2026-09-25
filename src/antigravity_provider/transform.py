from __future__ import annotations

import base64
import hashlib
import json
import secrets
import time
import uuid
from copy import deepcopy
from typing import Any

from .catalog import ModelCatalog, ResolvedRoute, fallback_catalog
from .models import normalize_effort

SKIP_THOUGHT_SIGNATURE = "skip_thought_signature_validator"




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
        return "\n".join(t for t in texts if t)
    return str(content)


def _parts_from_content(content: Any) -> list[dict[str, Any]]:
    if isinstance(content, list):
        parts: list[dict[str, Any]] = []
        for item in content:
            if not isinstance(item, dict):
                continue
            if item.get("type") == "text" and isinstance(item.get("text"), str) and item["text"].strip():
                parts.append({"text": item["text"]})
            elif item.get("type") == "image_url":
                url = (item.get("image_url") or {}).get("url") if isinstance(item.get("image_url"), dict) else None
                if isinstance(url, str) and url.startswith("data:") and ";base64," in url:
                    meta, data = url.split(",", 1)
                    mime = meta[5:].split(";", 1)[0] or "application/octet-stream"
                    # ponytail: trust data URL shape; provider validates bytes.
                    parts.append({"inlineData": {"mimeType": mime, "data": data}})
                else:
                    parts.append({"text": "[image omitted]"})
        return parts
    text = _content_text(content)
    return [{"text": text}] if text.strip() else []


def _parse_args(raw: Any) -> dict[str, Any]:
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str) and raw.strip():
        try:
            parsed = json.loads(raw)
            return parsed if isinstance(parsed, dict) else {"value": parsed}
        except json.JSONDecodeError:
            return {"value": raw}
    return {}


def _schema(schema: Any) -> dict[str, Any]:
    if not isinstance(schema, dict):
        return {"type": "object", "properties": {}}
    root = deepcopy(schema)
    banned = {"$schema", "$defs", "definitions", "additionalProperties", "patternProperties", "unevaluatedProperties"}

    def pointer(ref: str) -> Any:
        if not ref.startswith("#/"):
            raise ValueError(f"unsupported schema reference: {ref}")
        value: Any = root
        for token in ref[2:].split("/"):
            token = token.replace("~1", "/").replace("~0", "~")
            if not isinstance(value, dict) or token not in value:
                raise ValueError(f"unresolved schema reference: {ref}")
            value = value[token]
        return value

    def clean(value: Any, resolving: frozenset[str] = frozenset()) -> Any:
        if isinstance(value, dict):
            if isinstance(value.get("$ref"), str):
                ref = value["$ref"]
                if ref in resolving:
                    raise ValueError(f"cyclic schema reference: {ref}")
                resolved = clean(deepcopy(pointer(ref)), resolving | {ref})
                siblings = {key: nested for key, nested in value.items() if key != "$ref"}
                if siblings:
                    if not isinstance(resolved, dict):
                        raise ValueError(f"schema reference is not an object: {ref}")
                    resolved.update(clean(siblings, resolving))
                return resolved

            union_key = "anyOf" if "anyOf" in value else ("oneOf" if "oneOf" in value else None)
            if union_key:
                branches = value[union_key]
                if not isinstance(branches, list) or not branches:
                    raise ValueError("unsupported schema union: empty union")
                non_null = [
                    branch for branch in branches
                    if not (isinstance(branch, dict) and branch.get("type") == "null")
                ]
                if len(non_null) != 1 or len(non_null) == len(branches):
                    raise ValueError("unsupported schema union: only nullable unions are supported")
                merged = clean(non_null[0], resolving)
                siblings = {key: nested for key, nested in value.items() if key != union_key}
                if siblings:
                    if not isinstance(merged, dict):
                        raise ValueError("unsupported schema union")
                    merged.update(clean(siblings, resolving))
                return merged

            raw_type = value.get("type")
            if isinstance(raw_type, list):
                non_null_types = [item for item in raw_type if item != "null"]
                if len(non_null_types) != 1 or len(non_null_types) == len(raw_type):
                    raise ValueError("unsupported schema union: only nullable unions are supported")
                value = {**value, "type": non_null_types[0]}
            return {key: clean(nested, resolving) for key, nested in value.items() if key not in banned}
        if isinstance(value, list):
            return [clean(nested, resolving) for nested in value]
        return value

    out = clean(root)
    if "type" not in out:
        out["type"] = "object"
    if out.get("type") == "object":
        out.setdefault("properties", {})
    return out


def _tools(tools: list[dict[str, Any]]) -> list[dict[str, Any]] | None:
    declarations = []
    for tool in tools or []:
        if not isinstance(tool, dict) or tool.get("type") != "function":
            continue
        fn = tool.get("function") or {}
        if not isinstance(fn, dict) or not fn.get("name"):
            continue
        declarations.append(
            {
                "name": fn["name"],
                "description": fn.get("description") or "",
                "parameters": _schema(fn.get("parameters")),
            }
        )
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


def build_generate_content_request(
    *,
    model: str,
    project_id: str,
    messages: list[dict[str, Any]],
    tools: list[dict[str, Any]] | None = None,
    reasoning_effort: str | None = None,
    max_tokens: int | None = None,
    temperature: float | None = None,
    top_p: float | None = None,
    tool_choice: Any = None,
    session_id: str | None = None,
    catalog: ModelCatalog | None = None,
) -> dict[str, Any]:
    effort = normalize_effort(reasoning_effort)
    route = (catalog or fallback_catalog()).resolve(model, effort)
    actual_wire_model = route.wire_model

    system_parts: list[dict[str, str]] = []
    contents: list[dict[str, Any]] = []
    call_names: dict[str, str] = {}

    for msg in messages:
        role = msg.get("role")
        if role in {"system", "developer"}:
            text = _content_text(msg.get("content"))
            if text.strip():
                system_parts.append({"text": text})
        elif role == "user":
            parts = _parts_from_content(msg.get("content"))
            if parts:
                contents.append({"role": "user", "parts": parts})
        elif role == "assistant":
            parts = _parts_from_content(msg.get("content"))
            for tool_call in msg.get("tool_calls") or []:
                if not isinstance(tool_call, dict):
                    continue
                fn = tool_call.get("function") or {}
                name = fn.get("name") if isinstance(fn, dict) else None
                if not name:
                    continue
                if tool_call.get("id"):
                    call_names[str(tool_call["id"])] = name
                part = {"functionCall": {"name": name, "args": _parse_args(fn.get("arguments") if isinstance(fn, dict) else None)}}
                if (
                    actual_wire_model.startswith("gemini-3")
                    or actual_wire_model.startswith("gemini-pro")
                ):
                    part["thoughtSignature"] = SKIP_THOUGHT_SIGNATURE
                parts.append(part)
            if parts:
                contents.append({"role": "model", "parts": parts})
        elif role == "tool":
            name = msg.get("name") or call_names.get(str(msg.get("tool_call_id") or "")) or "tool"
            part = {"functionResponse": {"name": name, "response": {"output": _content_text(msg.get("content"))}}}
            if contents and contents[-1].get("role") == "user" and any("functionResponse" in p for p in contents[-1].get("parts", [])):
                contents[-1]["parts"].append(part)
            else:
                contents.append({"role": "user", "parts": [part]})

    if not contents:
        contents.append({"role": "user", "parts": [{"text": "Continue."}]})

    generation_config: dict[str, Any] = {
        "maxOutputTokens": (
            min(max_tokens, route.max_output_tokens)
            if isinstance(max_tokens, int) and max_tokens > 0
            else route.max_output_tokens
        ),
    }
    if route.thinking_budget is not None:
        generation_config["thinkingConfig"] = {
            "includeThoughts": route.include_thoughts,
            "thinkingBudget": route.thinking_budget,
        }
    if temperature is not None:
        generation_config["temperature"] = temperature
    if top_p is not None:
        generation_config["topP"] = top_p

    request: dict[str, Any] = {
        "contents": contents,
        "generationConfig": generation_config,
        "sessionId": _session_id(messages, session_id),
        "labels": _envelope_labels(route),
    }
    if system_parts:
        request["systemInstruction"] = {"role": "system", "parts": system_parts}
    converted_tools = _tools(tools or [])
    if converted_tools:
        request["tools"] = converted_tools
    config = _tool_config(tools or [], tool_choice, actual_wire_model)
    if config:
        request["toolConfig"] = config

    return {
        "project": project_id,
        "model": actual_wire_model,
        "request": request,
        "requestType": "agent",
        "userAgent": "antigravity",
        "requestId": f"agent/{uuid.uuid4()}/{int(time.time() * 1000)}/{uuid.uuid4()}/2",
    }
