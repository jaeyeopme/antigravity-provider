import unittest

from antigravity_provider.openai_compat import to_openai_completion
from antigravity_provider.transform import build_generate_content_request


class ToolCallTests(unittest.TestCase):
    def test_function_call_part_to_openai_tool_call(self):
        upstream = {"candidates": [{"content": {"parts": [{"functionCall": {"name": "get_time", "args": {}}}]}, "finishReason": "STOP"}]}
        out = to_openai_completion("google-antigravity/gemini-3.1-pro", upstream)
        msg = out["choices"][0]["message"]
        self.assertEqual(msg["tool_calls"][0]["function"]["name"], "get_time")
        self.assertEqual(out["choices"][0]["finish_reason"], "tool_calls")

    def test_tool_result_maps_to_function_response(self):
        body = build_generate_content_request(
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


if __name__ == "__main__":
    unittest.main()
