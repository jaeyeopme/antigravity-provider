import io
import unittest
import urllib.error
from unittest.mock import patch

from antigravity_provider.antigravity_client import AntigravityClient
from antigravity_provider.errors import ProxyError


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

    def test_thought_only_response_is_not_generated_twice(self):
        client = AntigravityClient()
        calls = []

        def stream_generate(**kwargs):
            calls.append(kwargs)
            yield {
                "candidates": [{
                    "content": {"parts": [{"text": "reasoning", "thought": True}]},
                    "finishReason": "STOP",
                }]
            }

        client.stream_generate = stream_generate
        out = client.generate(access_token="tok", body={"request": {}})
        self.assertEqual(len(calls), 1)
        self.assertTrue(out["candidates"][0]["content"]["parts"][0]["thought"])

    def test_empty_stream_is_an_error(self):
        client = AntigravityClient()
        client.stream_generate = lambda **kwargs: iter(())
        with self.assertRaisesRegex(ProxyError, "empty stream"):
            client.generate(access_token="tok", body={"request": {}})

    def test_404_falls_back_to_next_endpoint_before_streaming(self):
        calls = []

        class Response:
            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

            def __iter__(self):
                yield b'data: {"candidates":[{"content":{"parts":[{"text":"pong"}]},"finishReason":"STOP"}]}' + b"\n"
                yield b"\n"

        def fake_urlopen(request, timeout):
            calls.append(request.full_url)
            if len(calls) == 1:
                raise urllib.error.HTTPError(request.full_url, 404, "not found", {}, io.BytesIO(b"missing"))
            return Response()

        client = AntigravityClient(endpoints=["https://daily", "https://sandbox"])
        with patch("antigravity_provider.antigravity_client.urllib.request.urlopen", fake_urlopen):
            chunks = list(client.stream_generate(access_token="tok", body={"request": {}}))
        self.assertEqual(len(calls), 2)
        self.assertEqual(chunks[0]["candidates"][0]["content"]["parts"][0]["text"], "pong")


if __name__ == "__main__":
    unittest.main()
