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



if __name__ == "__main__":
    unittest.main()
