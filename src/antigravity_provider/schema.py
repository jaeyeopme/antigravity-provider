from __future__ import annotations

from copy import deepcopy
from typing import Any

# The only fields of the Gemini ``Schema`` message. Cloud Code parses function declarations into it
# for every model, so any other field (``const``, ``exclusiveMinimum``, ...) fails the request.
_SCHEMA_FIELDS = {
    "type",
    "format",
    "title",
    "description",
    "nullable",
    "enum",
    "maxItems",
    "minItems",
    "properties",
    "required",
    "minProperties",
    "maxProperties",
    "minLength",
    "maxLength",
    "pattern",
    "example",
    "anyOf",
    "propertyOrdering",
    "default",
    "items",
    "minimum",
    "maximum",
}


def _enum_string(value: Any) -> str | None:
    """Enum entries must be strings, whatever the declared type."""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (str, int, float)):
        return str(value)
    return None


def to_gemini_schema(schema: Any) -> dict[str, Any]:
    """Convert an OpenAI tool JSON Schema to the subset Cloud Code accepts.

    Local ``$ref``s are inlined (a recursive, remote, or missing one accepts any value), ``allOf``
    branches merge into one schema, nullable unions collapse to their non-null branch (marked ``nullable``), and other
    ``anyOf``/``oneOf`` unions widen into one permissive schema (properties unioned, ``required``
    intersected, enums merged) because the backend rejects unions in function declarations.
    Fields outside the Gemini ``Schema`` are dropped (``const`` becomes a one-value ``enum``), enum
    entries become strings, arrays always get ``items``, and ``required`` names only defined
    properties: the backend rejects the whole request otherwise.
    """
    if not isinstance(schema, dict):
        return {"type": "object", "properties": {}}
    root = deepcopy(schema)

    def pointer(ref: str) -> Any:
        """The local schema ``ref`` points to, or None for a remote or missing target."""
        if not ref.startswith("#/"):
            return None
        value: Any = root
        for token in ref[2:].split("/"):
            token = token.replace("~1", "/").replace("~0", "~")
            if not isinstance(value, dict) or token not in value:
                return None
            value = value[token]
        return value

    def combine(branches: list[Any]) -> dict[str, Any]:
        """``allOf``: one schema holding every branch's properties and requirements."""
        out: dict[str, Any] = {}
        for branch in branches:
            if not isinstance(branch, dict):
                continue
            for key, nested in branch.items():
                if key == "properties" and isinstance(nested, dict):
                    out.setdefault("properties", {}).update(
                        {
                            name: prop
                            for name, prop in nested.items()
                            if name not in out["properties"]
                        }
                    )
                elif key == "required" and isinstance(nested, list):
                    out["required"] = list(dict.fromkeys([*out.get("required", []), *nested]))
                else:
                    out.setdefault(key, nested)
        return out

    def widen(branches: list[Any]) -> dict[str, Any]:
        if not branches or not all(isinstance(branch, dict) for branch in branches):
            return {}
        if all(branch == branches[0] for branch in branches[1:]):
            return deepcopy(branches[0])

        descriptions = list(
            dict.fromkeys(
                branch["description"]
                for branch in branches
                if isinstance(branch.get("description"), str) and branch["description"]
            )
        )
        if all(branch.get("type") == "object" for branch in branches):
            property_names = dict.fromkeys(
                name for branch in branches for name in (branch.get("properties") or {})
            )
            properties = {}
            for name in property_names:
                candidates = [
                    branch["properties"][name]
                    for branch in branches
                    if name in (branch.get("properties") or {})
                ]
                properties[name] = (
                    widen(candidates) if len(candidates) > 1 else deepcopy(candidates[0])
                )
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
                target = pointer(ref)
                # A recursive, remote, or missing reference accepts any value there: failing would
                # reject every request while the tool is loaded.
                resolved = (
                    clean(deepcopy(target), resolving | {ref}) if ref not in resolving else {}
                )
                if not isinstance(resolved, dict):
                    resolved = {}
                siblings = {key: nested for key, nested in value.items() if key != "$ref"}
                if siblings:
                    resolved.update(clean(siblings, resolving))
                return resolved

            if isinstance(value.get("allOf"), list):
                siblings = {key: nested for key, nested in value.items() if key != "allOf"}
                return combine(
                    [
                        *(clean(branch, resolving) for branch in value["allOf"]),
                        clean(siblings, resolving),
                    ]
                )

            union_key = "anyOf" if "anyOf" in value else ("oneOf" if "oneOf" in value else None)
            if union_key:
                branches = value[union_key]
                if not isinstance(branches, list) or not branches:
                    branches = [{}]
                cleaned = [
                    clean(branch, resolving)
                    for branch in branches
                    if not (isinstance(branch, dict) and branch.get("type") == "null")
                ]
                merged = (
                    cleaned[0]
                    if len(cleaned) == 1 and isinstance(cleaned[0], dict)
                    else widen(cleaned)
                )
                if len(cleaned) < len(branches):
                    merged["nullable"] = True
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
                if len(non_null_types) < len(raw_type):
                    value["nullable"] = True
            if "const" in value and "enum" not in value:
                value = {**value, "enum": [value["const"]]}
            cleaned_value: dict[str, Any] = {}
            for key, nested in value.items():
                if key not in _SCHEMA_FIELDS:
                    continue
                if key == "properties" and isinstance(nested, dict):
                    # Keys here are parameter names, not schema keywords: keep them all.
                    cleaned_value[key] = {
                        name: clean(prop, resolving) for name, prop in nested.items()
                    }
                elif key == "items":
                    cleaned_value[key] = clean(nested, resolving)
                elif key == "enum" and isinstance(nested, list):
                    cleaned_value[key] = [
                        item for item in map(_enum_string, nested) if item is not None
                    ]
                else:
                    cleaned_value[key] = nested  # default/example values are data, not schemas
            if cleaned_value.get("type") == "array" and not isinstance(
                cleaned_value.get("items"), dict
            ):
                cleaned_value["items"] = {}
            if isinstance(cleaned_value.get("required"), list):
                defined = (
                    cleaned_value.get("properties")
                    if isinstance(cleaned_value.get("properties"), dict)
                    else {}
                )
                required = [name for name in cleaned_value["required"] if name in defined]
                if required:
                    cleaned_value["required"] = required
                else:
                    del cleaned_value["required"]
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
