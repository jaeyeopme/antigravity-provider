import time
import unittest

import antigravity_provider.runtime as runtime
from antigravity_provider.errors import TokenExpired


class FakeStore:
    def __init__(self, data):
        self.data = dict(data)
        self.saved = []

    def load(self):
        return dict(self.data)

    def save(self, data):
        self.data = dict(data)
        self.saved.append(dict(data))


class FakeClient:
    def __init__(self, fail_once=False):
        self.fail_once = fail_once
        self.calls = []

    def generate(self, *, access_token, body):
        self.calls.append((access_token, body))
        if self.fail_once:
            self.fail_once = False
            raise TokenExpired()
        return {"candidates": [{"content": {"parts": [{"text": "pong"}]}, "finishReason": "STOP"}]}


class RuntimeTests(unittest.TestCase):
    def setUp(self):
        runtime.clear_credential_cache()

    def tearDown(self):
        runtime.clear_credential_cache()

    def test_generate_chat_completion_in_process(self):
        old_keychain = runtime.load_agy_keychain_credentials
        try:
            runtime.load_agy_keychain_credentials = lambda: {}
            store = FakeStore({"access_token": "tok", "refresh_token": "ref", "project_id": "p", "expires_at": time.time() + 3600})
            client = FakeClient()
            completion = runtime.generate_chat_completion(
                {"model": "google-antigravity/gemini-3.1-pro", "messages": [{"role": "user", "content": "ping"}]},
                client=client,
                store=store,
            )
            self.assertEqual(completion["choices"][0]["message"]["content"], "pong")
            self.assertEqual(client.calls[0][0], "tok")
            self.assertEqual(client.calls[0][1]["project"], "p")
        finally:
            runtime.load_agy_keychain_credentials = old_keychain

    def test_browser_oauth_store_overrides_keychain(self):
        old_keychain = runtime.load_agy_keychain_credentials
        try:
            runtime.load_agy_keychain_credentials = lambda: {
                "access_token": "keychain",
                "refresh_token": "key-ref",
                "project_id": "key-project",
                "expires_at": time.time() + 3600,
            }
            store = FakeStore({
                "access_token": "browser",
                "refresh_token": "browser-ref",
                "project_id": "browser-project",
                "expires_at": time.time() + 3600,
            })
            creds = runtime.load_antigravity_credentials(store)
            self.assertEqual(creds["access_token"], "browser")
            self.assertEqual(creds["source"], "store")
        finally:
            runtime.load_agy_keychain_credentials = old_keychain

    def test_keychain_project_and_token_are_cached_for_process(self):
        old_keychain = runtime.load_agy_keychain_credentials
        old_project = runtime.load_or_onboard_project
        try:
            loads = []
            projects = []
            runtime.load_agy_keychain_credentials = lambda: loads.append(True) or {
                "access_token": "keychain",
                "refresh_token": "ref",
                "expires_at": time.time() + 3600,
            }
            runtime.load_or_onboard_project = lambda token: projects.append(token) or "p"
            store = FakeStore({})
            first = runtime.load_antigravity_credentials(store)
            second = runtime.load_antigravity_credentials(store)
            self.assertEqual(first, second)
            self.assertEqual(len(loads), 1)
            self.assertEqual(len(projects), 1)
        finally:
            runtime.load_agy_keychain_credentials = old_keychain
            runtime.load_or_onboard_project = old_project

    def test_keychain_refresh_is_reused_by_next_request(self):
        old_keychain = runtime.load_agy_keychain_credentials
        old_refresh = runtime.refresh_access_token
        try:
            refreshes = []
            runtime.load_agy_keychain_credentials = lambda: {
                "refresh_token": "ref",
                "project_id": "p",
                "source": "agy-keychain",
            }
            runtime.refresh_access_token = lambda refresh: refreshes.append(refresh) or {
                "access_token": "new",
                "refresh_token": "rotated",
                "expires_at": time.time() + 3600,
            }
            store = FakeStore({})
            first = runtime.load_antigravity_credentials(store)
            second = runtime.load_antigravity_credentials(store)
            self.assertEqual(first["access_token"], "new")
            self.assertEqual(second["access_token"], "new")
            self.assertEqual(refreshes, ["ref"])
            self.assertEqual(store.saved, [])
        finally:
            runtime.load_agy_keychain_credentials = old_keychain
            runtime.refresh_access_token = old_refresh

    def test_generate_refreshes_after_token_expired(self):
        old_keychain = runtime.load_agy_keychain_credentials
        old_refresh = runtime.refresh_access_token
        try:
            runtime.load_agy_keychain_credentials = lambda: {}
            runtime.refresh_access_token = lambda refresh: {
                "access_token": "new",
                "refresh_token": "rotated",
                "expires_at": time.time() + 3600,
            }
            store = FakeStore({"access_token": "old", "refresh_token": "ref", "project_id": "p", "expires_at": time.time() + 3600})
            client = FakeClient(fail_once=True)
            runtime.generate_chat_completion(
                {"model": "gemini-3.1-pro", "messages": [{"role": "user", "content": "ping"}]},
                client=client,
                store=store,
            )
            self.assertEqual(client.calls[0][0], "old")
            self.assertEqual(client.calls[1][0], "new")
            self.assertEqual(store.data["refresh_token"], "rotated")
        finally:
            runtime.load_agy_keychain_credentials = old_keychain
            runtime.refresh_access_token = old_refresh

    def test_stream_chat_completion_emits_real_chunks(self):
        class StreamingClient:
            def __init__(self):
                self.body = None

            def stream_generate(self, *, access_token, body):
                self.body = body
                yield {"candidates": [{"content": {"parts": [{"text": "thinking", "thought": True}]}}]}
                yield {
                    "candidates": [{"content": {"parts": [{"text": "pong"}]}, "finishReason": "STOP"}],
                    "usageMetadata": {"totalTokenCount": 2},
                }

        client = StreamingClient()
        store = FakeStore({
            "access_token": "tok",
            "refresh_token": "ref",
            "project_id": "p",
            "expires_at": time.time() + 3600,
        })
        chunks = list(runtime.stream_chat_completion(
            {"model": "gemini-3.1-pro", "messages": [{"role": "user", "content": "ping"}]},
            client=client,
            store=store,
            session_id="hermes-session",
        ))
        self.assertEqual(chunks[0].choices[0].delta.reasoning_content, "thinking")
        self.assertEqual(chunks[1].choices[0].delta.content, "pong")
        self.assertEqual(chunks[-1].choices[0].finish_reason, "stop")
        self.assertEqual(
            client.body["request"]["sessionId"],
            runtime.build_upstream_body(
                runtime.parse_chat_request({"model": "gemini-3.1-pro", "messages": [{"role": "user", "content": "ping"}]}),
                client=client,
                store=store,
                session_id="hermes-session",
            )[0]["request"]["sessionId"],
        )


if __name__ == "__main__":
    unittest.main()
