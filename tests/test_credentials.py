import base64
import json
import os
import tempfile
import unittest
from pathlib import Path

from ag_proxy.credentials import CredentialStore, load_agy_keychain_credentials, parse_agy_keychain_secret


class CredentialStoreTests(unittest.TestCase):
    def test_round_trip_credentials(self):
        with tempfile.TemporaryDirectory() as d:
            store = CredentialStore(Path(d) / "credentials.json")
            store.save({"refresh_token": "r", "access_token": "a", "project_id": "p", "expires_at": 123})
            self.assertEqual(store.load()["project_id"], "p")
            mode = os.stat(store.path).st_mode & 0o777
            self.assertEqual(mode, 0o600)
            store.delete()
            self.assertEqual(store.load(), {})

    def test_default_path_is_profile_scoped(self):
        old_home = os.environ.get("HERMES_HOME")
        with tempfile.TemporaryDirectory() as d:
            try:
                os.environ["HERMES_HOME"] = d
                store = CredentialStore.default()
                self.assertEqual(store.path, Path(d) / ".antigravity_oauth.json")
            finally:
                if old_home is None:
                    os.environ.pop("HERMES_HOME", None)
                else:
                    os.environ["HERMES_HOME"] = old_home

    def test_parse_agy_keychain_secret(self):
        payload = {
            "auth_method": "consumer",
            "token": {
                "access_token": "a",
                "refresh_token": "r",
                "token_type": "Bearer",
                "expiry": "2026-06-28T22:46:38+09:00",
            },
        }
        raw = "go-keyring-base64:" + base64.b64encode(json.dumps(payload).encode()).decode()
        parsed = parse_agy_keychain_secret(raw)
        self.assertEqual(parsed["source"], "agy-keychain")
        self.assertEqual(parsed["access_token"], "a")
        self.assertEqual(parsed["refresh_token"], "r")
        self.assertIsInstance(parsed["expires_at"], float)

    def test_load_agy_keychain_credentials_swallow_missing_keychain(self):
        self.assertEqual(load_agy_keychain_credentials(runner=lambda: "not-json"), {})

if __name__ == "__main__":
    unittest.main()
