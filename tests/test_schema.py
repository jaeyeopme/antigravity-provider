import unittest

from antigravity_provider.schema import to_gemini_schema


class SchemaTests(unittest.TestCase):
    def test_resolves_local_schema_refs_before_removing_defs(self):
        out = to_gemini_schema({
            "type": "object",
            "$defs": {"Item": {"type": "object", "properties": {"x": {"type": "string"}}}},
            "properties": {"item": {"$ref": "#/$defs/Item"}},
        })
        self.assertEqual(out["properties"]["item"]["properties"]["x"]["type"], "string")
        self.assertNotIn("$ref", out["properties"]["item"])
        self.assertNotIn("$defs", out)

    def test_keeps_parameters_named_like_schema_keywords(self):
        names = ["definitions", "additionalProperties", "$schema", "anyOf", "oneOf", "$ref"]
        out = to_gemini_schema({
            "type": "object",
            "properties": {name: {"type": "string"} for name in names},
            "required": names,
        })
        self.assertEqual(out["properties"], {name: {"type": "string"} for name in names})
        self.assertEqual(out["required"], names)

    def test_collapses_nullable_union(self):
        self.assertEqual(to_gemini_schema({"anyOf": [{"type": "string"}, {"type": "null"}]}), {"type": "string"})

    def test_widens_discriminated_object_union_without_dropping_branches(self):
        out = to_gemini_schema({
            "type": "object",
            "properties": {
                "operations": {
                    "type": "array",
                    "items": {
                        "anyOf": [
                            {
                                "type": "object",
                                "properties": {
                                    "name": {"type": "string"},
                                    "action": {"type": "string", "enum": ["create"]},
                                    "content": {"type": "string"},
                                },
                                "required": ["name", "action", "content"],
                            },
                            {
                                "type": "object",
                                "properties": {
                                    "name": {"type": "string"},
                                    "action": {"type": "string", "enum": ["delete"]},
                                    "absorbed_into": {"type": "string"},
                                },
                                "required": ["name", "action"],
                            },
                        ],
                    },
                },
            },
        })
        item = out["properties"]["operations"]["items"]
        self.assertNotIn("anyOf", item)
        self.assertEqual(item["properties"]["action"]["enum"], ["create", "delete"])
        self.assertEqual(
            set(item["properties"]),
            {"name", "action", "content", "absorbed_into"},
        )
        self.assertEqual(item["required"], ["action", "name"])

    def test_widens_mixed_type_union_without_choosing_one_branch(self):
        out = to_gemini_schema({
            "type": "object",
            "properties": {
                "notify": {
                    "description": "Boolean or channel list.",
                    "anyOf": [
                        {"type": "boolean"},
                        {"type": "array", "items": {"type": "string"}},
                    ],
                },
            },
        })
        notify = out["properties"]["notify"]
        self.assertEqual(notify, {"description": "Boolean or channel list."})
        self.assertNotIn("anyOf", notify)


    def test_keeps_only_fields_the_backend_schema_accepts(self):
        # Cloud Code rejects unknown fields like const/exclusiveMinimum for every model.
        out = to_gemini_schema({
            "type": "object",
            "properties": {
                "kind": {"type": "string", "const": "search", "examples": ["search"]},
                "limit": {"type": "integer", "exclusiveMinimum": 0, "minimum": 1, "default": 10},
            },
        })
        self.assertEqual(out["properties"]["kind"], {"type": "string", "enum": ["search"]})
        self.assertEqual(out["properties"]["limit"], {"type": "integer", "minimum": 1, "default": 10})

    def test_enum_values_become_strings(self):
        out = to_gemini_schema({"type": "object", "properties": {
            "level": {"type": "integer", "enum": [1, 2, 3]},
            "flag": {"type": "boolean", "enum": [True, False]},
        }})
        self.assertEqual(out["properties"]["level"]["enum"], ["1", "2", "3"])
        self.assertEqual(out["properties"]["flag"]["enum"], ["true", "false"])

    def test_array_without_items_gets_items(self):
        out = to_gemini_schema({"type": "object", "properties": {"tags": {"type": "array"}}})
        self.assertIn("items", out["properties"]["tags"])

    def test_required_lists_only_defined_properties(self):
        self.assertNotIn("required", to_gemini_schema({"type": "object", "required": ["query"]}))
        out = to_gemini_schema({"type": "object", "properties": {"a": {"type": "string"}}, "required": ["a", "b"]})
        self.assertEqual(out["required"], ["a"])

    def test_default_and_example_values_are_kept_verbatim(self):
        value = {"const": 1, "additionalProperties": True}
        out = to_gemini_schema({"type": "object", "properties": {"opts": {"type": "object", "default": value}}})
        self.assertEqual(out["properties"]["opts"]["default"], value)


if __name__ == "__main__":
    unittest.main()
