from __future__ import annotations

from copy import deepcopy
from typing import Any


def to_gemini_schema(schema: Any) -> dict[str, Any]:
    """Convert an OpenAI tool JSON Schema to the subset Cloud Code accepts.

    Local ``$ref``s are inlined, nullable unions collapse to their non-null branch, and other
    ``anyOf``/``oneOf`` unions widen into one permissive schema (properties unioned, ``required``
    intersected, enums merged) because the backend rejects unions in function declarations.
    """
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

    def widen(branches: list[Any]) -> dict[str, Any]:
        if not branches or not all(isinstance(branch, dict) for branch in branches):
            return {}
        if all(branch == branches[0] for branch in branches[1:]):
            return deepcopy(branches[0])

        descriptions = list(dict.fromkeys(
            branch["description"] for branch in branches
            if isinstance(branch.get("description"), str) and branch["description"]
        ))
        if all(branch.get("type") == "object" for branch in branches):
            property_names = dict.fromkeys(
                name
                for branch in branches
                for name in (branch.get("properties") or {})
            )
            properties = {}
            for name in property_names:
                candidates = [
                    branch["properties"][name]
                    for branch in branches
                    if name in (branch.get("properties") or {})
                ]
                properties[name] = widen(candidates) if len(candidates) > 1 else deepcopy(candidates[0])
            required = set(branches[0].get("required") or [])
            for branch in branches[1:]:
                required &= set(branch.get("required") or [])
            out: dict[str, Any] = {"type": "object", "properties": properties}
            if required:
                out["required"] = sorted(required)
        else:
            types = [branch.get("type") for branch in branches]
            out = (
                {"type": types[0]}
                if types[0] is not None and all(item == types[0] for item in types[1:])
                else {}
            )
            if all(isinstance(branch.get("enum"), list) for branch in branches):
                enum = []
                for branch in branches:
                    for item in branch["enum"]:
                        if item not in enum:
                            enum.append(deepcopy(item))
                out["enum"] = enum
            if out.get("type") == "array" and all("items" in branch for branch in branches):
                out["items"] = widen([branch["items"] for branch in branches])
        if descriptions:
            out["description"] = " / ".join(descriptions)
        return out

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
                cleaned = [
                    clean(branch, resolving) for branch in branches
                    if not (isinstance(branch, dict) and branch.get("type") == "null")
                ]
                merged = cleaned[0] if len(cleaned) == 1 and isinstance(cleaned[0], dict) else widen(cleaned)
                siblings = {key: nested for key, nested in value.items() if key != union_key}
                if siblings:
                    merged.update(clean(siblings, resolving))
                return merged

            raw_type = value.get("type")
            if isinstance(raw_type, list):
                non_null_types = [item for item in raw_type if item != "null"]
                value = {key: nested for key, nested in value.items() if key != "type"}
                if len(non_null_types) == 1:
                    value["type"] = non_null_types[0]
            cleaned_value: dict[str, Any] = {}
            for key, nested in value.items():
                if key in banned:
                    continue
                if key == "properties" and isinstance(nested, dict):
                    # Keys here are parameter names, not schema keywords: keep them all.
                    cleaned_value[key] = {name: clean(prop, resolving) for name, prop in nested.items()}
                else:
                    cleaned_value[key] = clean(nested, resolving)
            return cleaned_value
        if isinstance(value, list):
            return [clean(nested, resolving) for nested in value]
        return value

    out = clean(root)
    if "type" not in out:
        out["type"] = "object"
    if out.get("type") == "object":
        out.setdefault("properties", {})
    return out
