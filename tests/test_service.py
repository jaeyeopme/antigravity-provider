import tempfile
import time
import unittest
from pathlib import Path

from antigravity_provider.auth import CredentialManager
from antigravity_provider.catalog import CatalogManager
from antigravity_provider.credentials import CredentialStore, Credentials
from antigravity_provider.errors import AntigravityError, TokenExpired
from antigravity_provider.service import AntigravityService

PONG = {"candidates": [{"content": {"parts": [{"text": "pong"}]}, "finishReason": "STOP"}]}
PAYLOAD = {"model": "google-antigravity/gemini-3.1-pro", "messages": [{"role": "user", "content": "ping"}]}


class FakeClient:
    """Fails the first ``expire`` calls with 401, then streams ``events``."""

    def __init__(self, events=(PONG,), expire=0, models_expire=0):
        self.events = list(events)
        self.expire = expire
        self.models_expire = models_expire
        self.tokens = []
        self.bodies = []
        self.model_tokens = []

    def stream_generate(self, *, access_token, body):
        self.tokens.append(access_token)
        self.bodies.append(body)
        if self.expire:
            self.expire -= 1
            raise TokenExpired()
        yield from self.events

    def fetch_available_models(self, *, access_token, project_id):
        self.model_tokens.append(access_token)
        if self.models_expire:
            self.models_expire -= 1
            raise TokenExpired()
        return {"models": {"gemini-3.1-pro-low": {"maxOutputTokens": 1000}}}


class ServiceTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.store = CredentialStore(Path(tmp.name) / "oauth.json")
        self.store.save(Credentials(access_token="old", refresh_token="ref", project_id="p", expires_at=time.time() + 3600))
        self.refreshes = []
        self.credentials = CredentialManager(
            store_factory=lambda: self.store,
            keychain_loader=lambda: None,
            refresh_tokens=lambda token: self.refreshes.append(token) or {
                "access_token": "new", "refresh_token": "rotated", "expires_at": time.time() + 3600
            },
        )
        self.catalogs = CatalogManager(path=Path(tmp.name) / "models.json")

    def service(self, client):
        return AntigravityService(credentials=self.credentials, client=client, catalogs=self.catalogs)

    def test_complete_in_process(self):
        client = FakeClient()
        completion = self.service(client).complete(PAYLOAD)
        self.assertEqual(completion["choices"][0]["message"]["content"], "pong")
        self.assertEqual(client.tokens, ["old"])
        self.assertEqual(client.bodies[0]["project"], "p")

    def test_complete_refreshes_after_token_expired(self):
        client = FakeClient(expire=1)
        self.service(client).complete(PAYLOAD)
        self.assertEqual(client.tokens, ["old", "new"])
        self.assertEqual(self.store.load().refresh_token, "rotated")

    def test_stream_refreshes_after_token_expired_before_first_chunk(self):
        client = FakeClient(expire=1)
        chunks = list(self.service(client).stream(PAYLOAD))
        self.assertEqual(chunks[0]["choices"][0]["delta"]["content"], "pong")
        self.assertEqual(client.tokens, ["old", "new"])

    def test_stream_emits_reasoning_text_and_finish(self):
        events = [
            {"candidates": [{"content": {"parts": [{"text": "thinking", "thought": True}]}}]},
            {**PONG, "usageMetadata": {"totalTokenCount": 2}},
        ]
        chunks = list(self.service(FakeClient(events)).stream(PAYLOAD, session_id="hermes-session"))
        self.assertEqual(chunks[0]["choices"][0]["delta"]["reasoning_content"], "thinking")
        self.assertEqual(chunks[1]["choices"][0]["delta"]["content"], "pong")
        self.assertEqual(chunks[-1]["choices"][0]["finish_reason"], "stop")

    def test_session_id_is_stable_for_one_hermes_session(self):
        client = FakeClient()
        service = self.service(client)
        service.complete(PAYLOAD, session_id="s1")
        service.complete({**PAYLOAD, "messages": [{"role": "user", "content": "other"}]}, session_id="s1")
        service.complete(PAYLOAD, session_id="s2")
        ids = [body["request"]["sessionId"] for body in client.bodies]
        self.assertEqual(ids[0], ids[1])
        self.assertNotEqual(ids[0], ids[2])

    def test_empty_stream_is_an_error(self):
        with self.assertRaisesRegex(AntigravityError, "empty stream"):
            list(self.service(FakeClient(events=[])).stream(PAYLOAD))

    def test_model_discovery_refreshes_expired_token(self):
        client = FakeClient(models_expire=1)
        catalog = self.service(client).catalog()
        self.assertEqual(client.model_tokens, ["old", "new"])
        self.assertIn("google-antigravity/gemini-3.1-pro", catalog.model_ids())

    def test_invalid_payload_is_a_client_error(self):
        with self.assertRaises(AntigravityError) as raised:
            self.service(FakeClient()).complete({"model": "x", "messages": "nope"})
        self.assertEqual(raised.exception.status, 400)


if __name__ == "__main__":
    unittest.main()
