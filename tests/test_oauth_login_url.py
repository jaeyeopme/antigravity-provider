import os
import unittest

from antigravity_provider.oauth import build_auth_url


class OAuthLoginUrlTests(unittest.TestCase):
    def test_auth_url_uses_loopback_callback(self):
        url, verifier = build_auth_url(state="state-1")
        self.assertIn("accounts.google.com/o/oauth2/v2/auth", url)
        self.assertIn("redirect_uri=http%3A%2F%2F127.0.0.1%3A51121%2Foauth-callback", url)
        self.assertIn("code_challenge=", url)
        self.assertTrue(verifier)

    def test_auth_url_supports_container_bind_with_host_redirect(self):
        old_host = os.environ.get("ANTIGRAVITY_OAUTH_REDIRECT_HOST")
        old_port = os.environ.get("ANTIGRAVITY_OAUTH_PORT")
        try:
            os.environ["ANTIGRAVITY_OAUTH_REDIRECT_HOST"] = "localhost"
            os.environ["ANTIGRAVITY_OAUTH_PORT"] = "51122"
            url, _ = build_auth_url(state="state-1")
            self.assertIn("redirect_uri=http%3A%2F%2Flocalhost%3A51122%2Foauth-callback", url)
        finally:
            if old_host is None:
                os.environ.pop("ANTIGRAVITY_OAUTH_REDIRECT_HOST", None)
            else:
                os.environ["ANTIGRAVITY_OAUTH_REDIRECT_HOST"] = old_host
            if old_port is None:
                os.environ.pop("ANTIGRAVITY_OAUTH_PORT", None)
            else:
                os.environ["ANTIGRAVITY_OAUTH_PORT"] = old_port


if __name__ == "__main__":
    unittest.main()
