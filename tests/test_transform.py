import unittest

from antigravity_provider.transform import _schema, build_generate_content_request


class TransformTests(unittest.TestCase):
    def test_system_and_user_messages_are_preserved(self):
        body = build_generate_content_request(
            model="google-antigravity/gemini-3.1-pro",
            project_id="p",
            messages=[
                {"role": "system", "content": "You are concise."},
                {"role": "user", "content": "ping"},
            ],
            tools=[],
            reasoning_effort="low",
        )
        req = body["request"]
        self.assertIn("systemInstruction", req)
        self.assertEqual(req["systemInstruction"]["role"], "system")
        self.assertEqual(req["systemInstruction"]["parts"], [{"text": "You are concise."}])
        self.assertEqual(req["contents"][-1]["role"], "user")
        self.assertEqual(req["contents"][-1]["parts"][0]["text"], "ping")
        self.assertEqual(body["model"], "gemini-3.1-pro-low")
        self.assertEqual(req["generationConfig"]["thinkingConfig"]["thinkingBudget"], 1001)

    def test_openai_tool_schema_maps_to_function_declarations(self):
        body = build_generate_content_request(
            model="google-antigravity/gemini-3.1-pro",
            project_id="p",
            messages=[{"role": "user", "content": "call tool"}],
            tools=[{
                "type": "function",
                "function": {
                    "name": "get_time",
                    "description": "Get time",
                    "parameters": {"type": "object", "properties": {}, "additionalProperties": False},
                },
            }],
            reasoning_effort="low",
        )
        self.assertNotIn("systemInstruction", body["request"])
        tools = body["request"]["tools"]
        self.assertEqual(tools[0]["functionDeclarations"][0]["name"], "get_time")
        self.assertIn("parameters", tools[0]["functionDeclarations"][0])
        self.assertNotIn("additionalProperties", tools[0]["functionDeclarations"][0]["parameters"])
        self.assertEqual(body["request"]["toolConfig"]["functionCallingConfig"]["mode"], "VALIDATED")

    def test_gemini_38_flash_tiered_wire_routing(self):
        for effort, expected_budget in [("high", -1), ("medium", 4000), ("low", 1000)]:
            body = build_generate_content_request(
                model="google-antigravity/gemini-3.8-flash",
                project_id="p",
                messages=[{"role": "user", "content": "ping"}],
                reasoning_effort=effort,
            )
            self.assertEqual(body["model"], "gemini-3.8-flash-tiered")
            self.assertEqual(body["request"]["labels"]["model_enum"], "MODEL_PLACEHOLDER_M322")
            self.assertEqual(body["request"]["generationConfig"]["thinkingConfig"]["thinkingBudget"], expected_budget)

    def test_gemini_37_flash_tiered_wire_routing(self):
        body = build_generate_content_request(
            model="google-antigravity/gemini-3.7-flash",
            project_id="p",
            messages=[{"role": "user", "content": "ping"}],
            reasoning_effort="high",
        )
        self.assertEqual(body["model"], "gemini-3.7-flash-tiered")
        self.assertEqual(body["request"]["labels"]["model_enum"], "MODEL_PLACEHOLDER_M301")

    def test_gemini_36_flash_wire_routing(self):
        body = build_generate_content_request(
            model="google-antigravity/gemini-3.6-flash",
            project_id="p",
            messages=[{"role": "user", "content": "ping"}],
            reasoning_effort="high",
        )
        self.assertEqual(body["model"], "gemini-3.6-flash-high")
        self.assertEqual(body["request"]["labels"]["model_enum"], "MODEL_PLACEHOLDER_M71")

    def test_gpt_oss_120b_maps_to_medium_wire_model_and_labels(self):
        body = build_generate_content_request(
            model="google-antigravity/gpt-oss-120b",
            project_id="p",
            messages=[{"role": "user", "content": "ping"}],
            reasoning_effort="high",
        )
        self.assertEqual(body["model"], "gpt-oss-120b-medium")
        self.assertEqual(body["request"]["generationConfig"]["thinkingConfig"]["thinkingBudget"], 8192)
        self.assertEqual(body["request"]["labels"]["model_enum"], "MODEL_OPENAI_GPT_OSS_120B_MEDIUM")
        self.assertEqual(body["request"]["labels"]["used_non_gemini_model"], "true")

    def test_claude_labels_set_correctly(self):
        body = build_generate_content_request(
            model="google-antigravity/claude-sonnet-4-6",
            project_id="p",
            messages=[{"role": "user", "content": "ping"}],
            reasoning_effort="high",
        )
        self.assertEqual(body["model"], "claude-sonnet-4-6")
        self.assertEqual(body["request"]["labels"]["used_claude"], "true")
        self.assertEqual(body["request"]["labels"]["used_claude_conservative"], "true")

    def test_uses_real_hermes_session_identity(self):
        first = build_generate_content_request(
            model="gemini-3.1-pro",
            project_id="p",
            messages=[{"role": "user", "content": "hello"}],
            session_id="session-a",
        )
        second = build_generate_content_request(
            model="gemini-3.1-pro",
            project_id="p",
            messages=[{"role": "user", "content": "hello"}],
            session_id="session-b",
        )
        self.assertNotEqual(first["request"]["sessionId"], second["request"]["sessionId"])

    def test_resolves_local_schema_refs_before_removing_defs(self):
        out = _schema({
            "type": "object",
            "$defs": {"Item": {"type": "object", "properties": {"x": {"type": "string"}}}},
            "properties": {"item": {"$ref": "#/$defs/Item"}},
        })
        self.assertEqual(out["properties"]["item"]["properties"]["x"]["type"], "string")
        self.assertNotIn("$ref", out["properties"]["item"])
        self.assertNotIn("$defs", out)

    def test_collapses_nullable_union_only(self):
        self.assertEqual(_schema({"anyOf": [{"type": "string"}, {"type": "null"}]}), {"type": "string"})
        with self.assertRaisesRegex(ValueError, "unsupported schema union"):
            _schema({"anyOf": [{"type": "string"}, {"type": "integer"}]})


if __name__ == "__main__":
    unittest.main()
