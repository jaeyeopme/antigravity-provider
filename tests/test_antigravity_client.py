import unittest

from ag_proxy.antigravity_client import AntigravityClient


class AntigravityClientTests(unittest.TestCase):
    def test_posts_with_bearer_token(self):
        calls = []
        def fake_post(url, body, headers):
            calls.append((url, body, headers))
            return {"candidates": [{"content": {"parts": [{"text": "pong"}]}, "finishReason": "STOP"}]}

        client = AntigravityClient(post_json=fake_post)
        out = client.generate(access_token="tok", body={"request": {}})
        self.assertEqual(out["candidates"][0]["content"]["parts"][0]["text"], "pong")
        self.assertEqual(calls[0][2]["Authorization"], "Bearer tok")


if __name__ == "__main__":
    unittest.main()
