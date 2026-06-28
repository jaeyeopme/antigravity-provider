import unittest

from ag_proxy.openai_compat import parse_chat_request


class OpenAICompatTests(unittest.TestCase):
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
