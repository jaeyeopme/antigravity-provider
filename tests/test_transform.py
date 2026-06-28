import unittest

from antigravity_provider.transform import build_generate_content_request


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

    def test_gpt_oss_120b_maps_to_maas_wire_model(self):
        body = build_generate_content_request(
            model="google-antigravity/gpt-oss-120b",
            project_id="p",
            messages=[{"role": "user", "content": "ping"}],
            reasoning_effort="high",
        )
        self.assertEqual(body["model"], "openai/gpt-oss-120b-maas")
        self.assertEqual(body["request"]["generationConfig"]["thinkingConfig"]["thinkingBudget"], 8192)


if __name__ == "__main__":
    unittest.main()
