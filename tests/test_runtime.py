import time
import unittest

import ag_proxy.runtime as runtime
from ag_proxy.errors import TokenExpired


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

    def test_agy_keychain_overrides_file_and_does_not_save(self):
        old_keychain = runtime.load_agy_keychain_credentials
        old_refresh = runtime.refresh_access_token
        try:
            runtime.load_agy_keychain_credentials = lambda: {
                "refresh_token": "env-ref",
                "project_id": "p",
                "source": "agy-keychain",
            }
            runtime.refresh_access_token = lambda refresh: {
                "access_token": "keychain",
                "refresh_token": refresh,
                "expires_at": time.time() + 3600,
            }
            store = FakeStore({"access_token": "file", "refresh_token": "file-ref", "project_id": "file-p"})
            creds = runtime.load_antigravity_credentials(store)
            self.assertEqual(creds["access_token"], "keychain")
            self.assertEqual(creds["source"], "agy-keychain")
            self.assertEqual(store.saved, [])
        finally:
            runtime.load_agy_keychain_credentials = old_keychain
            runtime.refresh_access_token = old_refresh

    def test_agy_keychain_refresh_does_not_save_file(self):
        old_keychain = runtime.load_agy_keychain_credentials
        old_refresh = runtime.refresh_access_token
        try:
            runtime.load_agy_keychain_credentials = lambda: {
                "refresh_token": "ref",
                "project_id": "p",
                "source": "agy-keychain",
            }
            tokens = iter(["old", "new"])
            runtime.refresh_access_token = lambda refresh: {
                "access_token": next(tokens),
                "refresh_token": "rotated",
                "expires_at": time.time() + 3600,
            }
            store = FakeStore({})
            client = FakeClient(fail_once=True)
            runtime.generate_chat_completion(
                {"model": "gemini-3.1-pro", "messages": [{"role": "user", "content": "ping"}]},
                client=client,
                store=store,
            )
            self.assertEqual(client.calls[0][0], "old")
            self.assertEqual(client.calls[1][0], "new")
            self.assertEqual(store.saved, [])
        finally:
            runtime.load_agy_keychain_credentials = old_keychain
            runtime.refresh_access_token = old_refresh

    def test_generate_refreshes_after_token_expired(self):
        old_keychain = runtime.load_agy_keychain_credentials
        old = runtime.refresh_access_token
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
            runtime.refresh_access_token = old


if __name__ == "__main__":
    unittest.main()
