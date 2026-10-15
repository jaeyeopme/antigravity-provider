import unittest

from antigravity_provider.request import ChatRequest, parse_chat_request, SKIP_THOUGHT_SIGNATURE, build_generate_content_request
from antigravity_provider.errors import AntigravityError
from antigravity_provider.models import normalize_model_id


def build(*, model, messages, project_id="p", tools=None, reasoning_effort=None, session_id=None, tool_choice=None):
    request = ChatRequest(
        model=normalize_model_id(model),
        messages=messages,
        tools=tools or [],
        tool_choice=tool_choice,
        reasoning_effort=reasoning_effort,
    )
    return build_generate_content_request(request, project_id=project_id, session_id=session_id)


class RequestTests(unittest.TestCase):
    def test_system_and_user_messages_are_preserved(self):
        body = build(
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
        body = build(
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
            body = build(
                model="google-antigravity/gemini-3.8-flash",
                project_id="p",
                messages=[{"role": "user", "content": "ping"}],
                reasoning_effort=effort,
            )
            self.assertEqual(body["model"], "gemini-3.8-flash-tiered")
            self.assertEqual(body["request"]["labels"]["model_enum"], "MODEL_PLACEHOLDER_M322")
            self.assertEqual(body["request"]["generationConfig"]["thinkingConfig"]["thinkingBudget"], expected_budget)

    def test_gemini_37_flash_tiered_wire_routing(self):
        body = build(
            model="google-antigravity/gemini-3.7-flash",
            project_id="p",
            messages=[{"role": "user", "content": "ping"}],
            reasoning_effort="high",
        )
        self.assertEqual(body["model"], "gemini-3.7-flash-tiered")
        self.assertEqual(body["request"]["labels"]["model_enum"], "MODEL_PLACEHOLDER_M301")

    def test_gemini_36_flash_wire_routing(self):
        body = build(
            model="google-antigravity/gemini-3.6-flash",
            project_id="p",
            messages=[{"role": "user", "content": "ping"}],
            reasoning_effort="high",
        )
        self.assertEqual(body["model"], "gemini-3.6-flash-high")
        self.assertEqual(body["request"]["labels"]["model_enum"], "MODEL_PLACEHOLDER_M71")

    def test_gpt_oss_120b_maps_to_medium_wire_model_and_labels(self):
        body = build(
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
        body = build(
            model="google-antigravity/claude-sonnet-4-6",
            project_id="p",
            messages=[{"role": "user", "content": "ping"}],
            reasoning_effort="high",
        )
        self.assertEqual(body["model"], "claude-sonnet-4-6")
        self.assertEqual(body["request"]["labels"]["used_claude"], "true")
        self.assertEqual(body["request"]["labels"]["used_claude_conservative"], "true")

    def test_uses_real_hermes_session_identity(self):
        first = build(
            model="gemini-3.1-pro",
            project_id="p",
            messages=[{"role": "user", "content": "hello"}],
            session_id="session-a",
        )
        second = build(
            model="gemini-3.1-pro",
            project_id="p",
            messages=[{"role": "user", "content": "hello"}],
            session_id="session-b",
        )
        self.assertNotEqual(first["request"]["sessionId"], second["request"]["sessionId"])

    def test_tool_result_maps_to_function_response(self):
        body = build(
            model="google-antigravity/gemini-3.1-pro",
            project_id="p",
            messages=[
                {"role": "assistant", "tool_calls": [{"id": "call_1", "type": "function", "function": {"name": "get_time", "arguments": "{}"}}]},
                {"role": "tool", "tool_call_id": "call_1", "content": '{"time":"now"}'},
            ],
            tools=[],
            reasoning_effort="low",
        )
        response = body["request"]["contents"][-1]["parts"][0]["functionResponse"]
        self.assertEqual(response["name"], "get_time")
        self.assertEqual(response["response"]["output"], '{"time":"now"}')


    def _tool_history(self, model, extra_content=None):
        tool_call = {"id": "c1", "type": "function", "function": {"name": "f", "arguments": "{}"}}
        if extra_content is not None:
            tool_call["extra_content"] = extra_content
        return build(
            model=model,
            messages=[
                {"role": "user", "content": "hi"},
                {"role": "assistant", "content": None, "tool_calls": [tool_call]},
                {"role": "tool", "tool_call_id": "c1", "content": "ok"},
            ],
        )

    def test_replays_real_thought_signature_from_hermes_history(self):
        body = self._tool_history("gemini-3.1-pro", {"google": {"thought_signature": "REAL"}})
        self.assertEqual(body["request"]["contents"][1]["parts"][0]["thoughtSignature"], "REAL")

    def test_accepts_flat_thought_signature(self):
        body = self._tool_history("gemini-3.1-pro", {"thought_signature": "FLAT"})
        self.assertEqual(body["request"]["contents"][1]["parts"][0]["thoughtSignature"], "FLAT")

    def test_uses_placeholder_signature_only_when_history_has_none(self):
        body = self._tool_history("gemini-3.1-pro")
        self.assertEqual(body["request"]["contents"][1]["parts"][0]["thoughtSignature"], SKIP_THOUGHT_SIGNATURE)

    def test_non_gemini3_route_gets_no_placeholder_signature(self):
        body = self._tool_history("claude-sonnet-4-6")
        self.assertNotIn("thoughtSignature", body["request"]["contents"][1]["parts"][0])

    def test_parallel_calls_keep_signature_only_where_backend_put_it(self):
        calls = [
            {"id": "a", "type": "function", "function": {"name": "f", "arguments": "{}"},
             "extra_content": {"google": {"thought_signature": "SIG"}}},
            {"id": "b", "type": "function", "function": {"name": "g", "arguments": "{}"}},
        ]
        body = build(model="gemini-3.1-pro", messages=[{"role": "assistant", "tool_calls": calls}])
        parts = body["request"]["contents"][0]["parts"]
        self.assertEqual(parts[0]["thoughtSignature"], "SIG")
        self.assertNotIn("thoughtSignature", parts[1])

    def test_unsupported_tool_schema_is_a_client_error_naming_the_tool(self):
        tools = [{"type": "function", "function": {"name": "bad", "parameters": {"$ref": "https://x/schema"}}}]
        with self.assertRaises(AntigravityError) as raised:
            build(model="gemini-3.1-pro", messages=[{"role": "user", "content": "x"}], tools=tools)
        self.assertEqual(raised.exception.status, 400)
        self.assertIn("'bad'", raised.exception.message)

    def test_parses_model_messages_and_reasoning(self):
        req = parse_chat_request({
            "model": "gemini-3.1-pro",
            "reasoning_effort": "high",
            "messages": [{"role": "user", "content": "ping"}],
        })
        self.assertEqual(req.model, "google-antigravity/gemini-3.1-pro")
        self.assertEqual(req.reasoning_effort, "high")
        self.assertEqual(req.messages[0]["content"], "ping")

    def test_parses_hermes_extra_body_reasoning_and_completion_tokens(self):
        req = parse_chat_request({
            "model": "gemini-3.1-pro",
            "messages": [{"role": "user", "content": "ping"}],
            "extra_body": {"reasoning": {"effort": "low"}},
            "max_completion_tokens": 123,
        })
        self.assertEqual(req.reasoning_effort, "low")
        self.assertEqual(req.max_tokens, 123)



if __name__ == "__main__":
    unittest.main()
