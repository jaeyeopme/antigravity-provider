import unittest

from antigravity_provider.openai_compat import to_openai_completion, to_openai_stream_chunks


class OpenAIResponseTests(unittest.TestCase):
    def test_text_candidate_to_completion(self):
        completion = to_openai_completion(
            model="google-antigravity/gemini-3.1-pro",
            upstream={"candidates": [{"content": {"parts": [{"text": "pong"}]}, "finishReason": "STOP"}]},
        )
        self.assertEqual(completion["object"], "chat.completion")
        self.assertEqual(completion["choices"][0]["message"]["content"], "pong")
        self.assertEqual(completion["choices"][0]["finish_reason"], "stop")

    def test_stream_events_are_emitted_as_reasoning_text_tool_and_finish_chunks(self):
        events = [
            {"candidates": [{"content": {"parts": [{"text": "think", "thought": True}]}}]},
            {"candidates": [{"content": {"parts": [{"text": "answer"}]}}]},
            {
                "candidates": [{
                    "content": {"parts": [{"functionCall": {"name": "lookup", "args": {"q": "x"}}}]},
                    "finishReason": "STOP",
                }],
                "usageMetadata": {"promptTokenCount": 2, "candidatesTokenCount": 3, "totalTokenCount": 5},
            },
        ]
        chunks = list(to_openai_stream_chunks("gemini-3.1-pro", events))
        self.assertEqual(chunks[0]["choices"][0]["delta"]["reasoning_content"], "think")
        self.assertEqual(chunks[1]["choices"][0]["delta"]["content"], "answer")
        self.assertEqual(chunks[2]["choices"][0]["delta"]["tool_calls"][0]["function"]["name"], "lookup")
        self.assertEqual(chunks[-1]["choices"][0]["finish_reason"], "tool_calls")
        self.assertEqual(chunks[-1]["usage"]["total_tokens"], 5)


if __name__ == "__main__":
    unittest.main()
