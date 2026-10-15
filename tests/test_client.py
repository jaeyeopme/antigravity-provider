import io
import unittest
import urllib.error
from unittest.mock import patch

from antigravity_provider.client import AntigravityClient, _merge_model_catalogs, _sse_events
from antigravity_provider.errors import AntigravityError, TokenExpired

PONG = b'data: {"candidates":[{"content":{"parts":[{"text":"pong"}]},"finishReason":"STOP"}]}\n'


class Response:
    def __init__(self, lines):
        self.lines = lines
        self.closed = False

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.closed = True
        return False

    def __iter__(self):
        yield from self.lines


def http_error(url, code, body=b""):
    return urllib.error.HTTPError(url, code, "error", {}, io.BytesIO(body))


class StreamTests(unittest.TestCase):
    def stream(self, fake_urlopen, endpoints=("https://daily", "https://sandbox")):
        client = AntigravityClient(endpoints=list(endpoints))
        with patch("antigravity_provider.client.urllib.request.urlopen", fake_urlopen):
            return list(client.stream_generate(access_token="tok", body={"request": {}}))

    def test_404_falls_back_to_next_endpoint_before_streaming(self):
        calls = []

        def fake_urlopen(request, timeout):
            calls.append(request.full_url)
            if len(calls) == 1:
                raise http_error(request.full_url, 404, b"missing")
            return Response([PONG, b"\n"])

        chunks = self.stream(fake_urlopen)
        self.assertEqual(len(calls), 2)
        self.assertEqual(chunks[0]["candidates"][0]["content"]["parts"][0]["text"], "pong")

    def test_401_is_token_expired_without_trying_next_endpoint(self):
        calls = []

        def fake_urlopen(request, timeout):
            calls.append(request.full_url)
            raise http_error(request.full_url, 401)

        with self.assertRaises(TokenExpired):
            self.stream(fake_urlopen)
        self.assertEqual(len(calls), 1)

    def test_400_is_not_retried_on_next_endpoint(self):
        calls = []

        def fake_urlopen(request, timeout):
            calls.append(request.full_url)
            raise http_error(request.full_url, 400, b"bad request")

        with self.assertRaises(AntigravityError) as raised:
            self.stream(fake_urlopen)
        self.assertEqual(raised.exception.status, 400)
        self.assertEqual(len(calls), 1)

    def test_in_stream_error_event_is_raised(self):
        line = b'data: {"error":{"code":429,"message":"quota"}}\n'
        with self.assertRaisesRegex(AntigravityError, "quota"):
            self.stream(lambda request, timeout: Response([line, b"\n"]), endpoints=("https://only",))

    def test_closing_the_stream_closes_the_http_response(self):
        response = Response([PONG, b"\n", PONG, b"\n"])
        client = AntigravityClient(endpoints=["https://only"])
        with patch("antigravity_provider.client.urllib.request.urlopen", lambda request, timeout: response):
            stream = client.stream_generate(access_token="tok", body={})
            next(stream)
            stream.close()
        self.assertTrue(response.closed)


class ParsingTests(unittest.TestCase):
    def test_sse_multiline_data_comments_and_done(self):
        lines = [b": keepalive\n", b'data: {"a":\n', b"data: 1}\n", b"\n", b"data: [DONE]\n", b"\n"]
        self.assertEqual(list(_sse_events(lines)), [{"a": 1}])

    def test_sse_trailing_event_without_blank_line(self):
        self.assertEqual(list(_sse_events([b'data: {"a":2}\n'])), [{"a": 2}])

    def test_model_catalog_merge_keeps_first_scalar_and_unions_lists(self):
        merged = _merge_model_catalogs([
            {"defaultAgentModelId": "a", "models": {"x": {}}, "ids": [1]},
            {"defaultAgentModelId": "b", "models": {"y": {}}, "ids": [1, 2]},
        ])
        self.assertEqual(merged, {"defaultAgentModelId": "a", "models": {"x": {}, "y": {}}, "ids": [1, 2]})


if __name__ == "__main__":
    unittest.main()
