import os
import threading
import unittest
import urllib.error
import urllib.request
from unittest.mock import patch

from antigravity_provider import oauth
from antigravity_provider.errors import AntigravityError


class TokenTests(unittest.TestCase):
    def test_oauth_client_is_bundled(self):
        client_id, client_secret = oauth.oauth_client()
        self.assertEqual(client_id.split("-", 1)[0], "1071006060591")
        self.assertTrue(client_id.endswith(".apps.googleusercontent.com"))
        self.assertTrue(client_secret.startswith("GOCSPX-"))

    def test_refresh_access_token(self):
        calls = []

        def fake_post(url, form):
            calls.append((url, form))
            return {"access_token": "new-access", "expires_in": 3600, "token_type": "Bearer"}

        refreshed = oauth.refresh_access_token(
            "refresh-token", post_form=fake_post, client=("id", "secret")
        )
        self.assertEqual(refreshed["access_token"], "new-access")
        self.assertEqual(refreshed["refresh_token"], "refresh-token")
        self.assertGreater(refreshed["expires_at"], 0)
        self.assertEqual(calls[0][1]["grant_type"], "refresh_token")

    def test_refresh_access_token_keeps_rotated_refresh_token(self):
        def fake_post(url, form):
            return {
                "access_token": "new-access",
                "refresh_token": "new-refresh",
                "expires_in": 3600,
            }

        refreshed = oauth.refresh_access_token(
            "old-refresh", post_form=fake_post, client=("id", "secret")
        )
        self.assertEqual(refreshed["refresh_token"], "new-refresh")

    def test_revoked_refresh_token_asks_for_a_new_sign_in(self):
        def fake_post(url, form):
            raise AntigravityError(
                'OAuth token request failed (400): {"error": "invalid_grant"}', status=400
            )

        with self.assertRaises(AntigravityError) as raised:
            oauth.refresh_access_token("revoked", post_form=fake_post, client=("id", "secret"))
        self.assertEqual(raised.exception.status, 401)
        self.assertIn("hermes agy login", raised.exception.message)

    def test_other_refresh_failures_pass_through(self):
        def fake_post(url, form):
            raise AntigravityError("OAuth token request failed: timed out", status=502)

        with self.assertRaises(AntigravityError) as raised:
            oauth.refresh_access_token("ref", post_form=fake_post, client=("id", "secret"))
        self.assertEqual(raised.exception.status, 502)

    def test_code_exchange_requires_refresh_token(self):
        with self.assertRaisesRegex(AntigravityError, "No refresh token"):
            oauth.exchange_code_for_tokens(
                "code",
                redirect_uri="http://x",
                code_verifier="v",
                post_form=lambda url, form: {"access_token": "a"},
            )

    def test_user_email_lookup_failure_never_breaks_login(self):
        def reset(*args, **kwargs):
            raise ConnectionResetError("reset")

        with patch("antigravity_provider.net.urllib.request.urlopen", reset):
            self.assertIsNone(oauth.fetch_user_email("tok"))


class LoginUrlTests(unittest.TestCase):
    def test_auth_url_uses_loopback_callback(self):
        url, verifier = oauth.build_auth_url("state-1")
        self.assertIn("accounts.google.com/o/oauth2/v2/auth", url)
        self.assertIn("redirect_uri=http%3A%2F%2F127.0.0.1%3A51121%2Foauth-callback", url)
        self.assertIn("code_challenge=", url)
        self.assertIn("state=state-1", url)
        self.assertTrue(verifier)

    def test_auth_url_supports_container_bind_with_host_redirect(self):
        env = {"ANTIGRAVITY_OAUTH_REDIRECT_HOST": "localhost", "ANTIGRAVITY_OAUTH_PORT": "51122"}
        with patch.dict(os.environ, env):
            url, _ = oauth.build_auth_url("state-1")
        self.assertIn("redirect_uri=http%3A%2F%2Flocalhost%3A51122%2Foauth-callback", url)


class CallbackServerTests(unittest.TestCase):
    def request(self, server, query):
        port = server.server_address[1]
        try:
            with urllib.request.urlopen(
                f"http://127.0.0.1:{port}/oauth-callback?{query}"
            ) as response:
                return response.status
        except urllib.error.HTTPError as exc:
            return exc.code

    def serve_one(self, server, query):
        result = {}
        thread = threading.Thread(
            target=lambda: result.setdefault("status", self.request(server, query))
        )
        thread.start()
        server.handle_request()
        thread.join(5)
        return result["status"]

    def test_request_with_wrong_state_is_ignored(self):
        server = oauth._CallbackServer(("127.0.0.1", 0), "expected")
        try:
            self.assertEqual(self.serve_one(server, "code=attacker&state=wrong"), 400)
            self.assertIsNone(server.received_code)
            self.assertEqual(self.serve_one(server, "code=real&state=expected"), 200)
            self.assertEqual(server.received_code, "real")
        finally:
            server.server_close()

    def test_error_with_wrong_state_does_not_abort_login(self):
        server = oauth._CallbackServer(("127.0.0.1", 0), "expected")
        try:
            self.serve_one(server, "error=access_denied&state=wrong")
            self.assertIsNone(server.received_error)
        finally:
            server.server_close()


if __name__ == "__main__":
    unittest.main()
