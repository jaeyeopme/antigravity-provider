import unittest

from antigravity_provider.openai_compat import to_openai_completion


class OpenAIResponseTests(unittest.TestCase):
    def test_text_candidate_to_completion(self):
        completion = to_openai_completion(
            model="google-antigravity/gemini-3.1-pro",
            upstream={"candidates": [{"content": {"parts": [{"text": "pong"}]}, "finishReason": "STOP"}]},
        )
        self.assertEqual(completion["object"], "chat.completion")
        self.assertEqual(completion["choices"][0]["message"]["content"], "pong")
        self.assertEqual(completion["choices"][0]["finish_reason"], "stop")


if __name__ == "__main__":
    unittest.main()
