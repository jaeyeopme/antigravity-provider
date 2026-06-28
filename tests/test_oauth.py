import tempfile
import unittest
from pathlib import Path

import antigravity_provider.oauth as oauth_module
from antigravity_provider.credentials import CredentialStore
from antigravity_provider.oauth import oauth_client, refresh_access_token, refresh_if_needed


class OAuthTests(unittest.TestCase):
    def test_oauth_client_is_bundled(self):
        client_id, client_secret = oauth_client()
        self.assertEqual(client_id.split("-", 1)[0], "1071006060591")
        self.assertTrue(client_id.endswith(".apps.googleusercontent.com"))
        self.assertTrue(client_secret.startswith("GOCSPX-"))

    def test_refresh_access_token(self):
        calls = []
        def fake_post(url, data, headers):
            calls.append((url, data, headers))
            return {"access_token": "new-access", "expires_in": 3600, "token_type": "Bearer"}

        refreshed = refresh_access_token("refresh-token", post_json=fake_post, client=("client-id", "client-secret"))
        self.assertEqual(refreshed["access_token"], "new-access")
        self.assertEqual(refreshed["refresh_token"], "refresh-token")
        self.assertGreater(refreshed["expires_at"], 0)
        self.assertIn("refresh_token", calls[0][1])

    def test_refresh_access_token_keeps_rotated_refresh_token(self):
        def fake_post(url, data, headers):
            return {"access_token": "new-access", "refresh_token": "new-refresh", "expires_in": 3600}

        refreshed = refresh_access_token("old-refresh", post_json=fake_post, client=("client-id", "client-secret"))
        self.assertEqual(refreshed["refresh_token"], "new-refresh")

    def test_refresh_if_needed_uses_existing_fresh_token(self):
        credentials = {"access_token": "a", "refresh_token": "r", "expires_at": 9999999999}
        self.assertIs(refresh_if_needed(credentials), credentials)

    def test_login_imports_keychain_before_browser_oauth(self):
        old_load = oauth_module.load_agy_keychain_credentials
        old_project = oauth_module.load_or_onboard_project
        old_email = oauth_module.fetch_user_email
        try:
            oauth_module.load_agy_keychain_credentials = lambda: {
                "access_token": "a",
                "refresh_token": "r",
                "expires_at": 9999999999,
                "source": "agy-keychain",
            }
            oauth_module.load_or_onboard_project = lambda access: "p"
            oauth_module.fetch_user_email = lambda access: "user@example.com"
            with tempfile.TemporaryDirectory() as d:
                store = CredentialStore(Path(d) / "credentials.json")
                credentials = oauth_module.run_login(open_browser=False, timeout=0, store=store)
                self.assertEqual(credentials["project_id"], "p")
                self.assertEqual(store.load(), {})
        finally:
            oauth_module.load_agy_keychain_credentials = old_load
            oauth_module.load_or_onboard_project = old_project
            oauth_module.fetch_user_email = old_email


if __name__ == "__main__":
    unittest.main()
