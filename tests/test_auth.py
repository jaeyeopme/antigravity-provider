import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from antigravity_provider import oauth
from antigravity_provider.auth import CredentialManager
from antigravity_provider.credentials import SOURCE_BROWSER, SOURCE_KEYCHAIN, CredentialStore, Credentials
from antigravity_provider.errors import AntigravityError, TokenExpired


def fresh(**overrides):
    values = {"access_token": "tok", "refresh_token": "ref", "project_id": "p", "expires_at": time.time() + 3600}
    values.update(overrides)
    return values


class Harness:
    def __init__(self, directory, keychain=None):
        self.store = CredentialStore(Path(directory) / "oauth.json")
        self.keychain = keychain
        self.keychain_loads = 0
        self.refreshes = []
        self.projects = []
        self.manager = CredentialManager(
            store_factory=lambda: self.store,
            keychain_loader=self.load_keychain,
            refresh_tokens=self.refresh,
            discover_project=lambda token: self.projects.append(token) or "discovered",
            fetch_email=lambda token: "user@example.com",
        )

    def load_keychain(self):
        self.keychain_loads += 1
        return Credentials.from_mapping(self.keychain, source=SOURCE_KEYCHAIN) if self.keychain else None

    def refresh(self, refresh_token):
        self.refreshes.append(refresh_token)
        return {"access_token": f"new-{len(self.refreshes)}", "refresh_token": "rotated", "expires_at": time.time() + 3600}


class CurrentCredentialTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def test_browser_oauth_store_overrides_keychain(self):
        h = Harness(self.tmp.name, keychain=fresh(access_token="keychain"))
        h.store.save(Credentials.from_mapping(fresh(access_token="browser"), source=SOURCE_BROWSER))
        creds = h.manager.current()
        self.assertEqual((creds.access_token, creds.source), ("browser", SOURCE_BROWSER))
        self.assertEqual(h.keychain_loads, 0)

    def test_expired_browser_token_is_refreshed_and_saved(self):
        h = Harness(self.tmp.name)
        h.store.save(Credentials.from_mapping(fresh(expires_at=time.time() - 1), source=SOURCE_BROWSER))
        self.assertEqual(h.manager.current().access_token, "new-1")
        self.assertEqual(h.store.load().refresh_token, "rotated")

    def test_keychain_project_and_token_are_cached_for_process(self):
        h = Harness(self.tmp.name, keychain=fresh(project_id=""))
        first = h.manager.current()
        second = h.manager.current()
        self.assertEqual(first, second)
        self.assertEqual(first.project_id, "discovered")
        self.assertEqual((h.keychain_loads, len(h.projects)), (1, 1))

    def test_keychain_refresh_is_reused_and_never_written_to_store(self):
        h = Harness(self.tmp.name, keychain={"refresh_token": "ref", "project_id": "p"})
        self.assertEqual(h.manager.current().access_token, "new-1")
        self.assertEqual(h.manager.current().access_token, "new-1")
        self.assertEqual(h.refreshes, ["ref"])
        self.assertIsNone(h.store.load())

    def test_unreadable_keychain_is_read_again_on_the_next_request(self):
        h = Harness(self.tmp.name)  # e.g. the Keychain was locked when Hermes started
        with self.assertRaises(AntigravityError):
            h.manager.current()
        h.keychain = fresh(access_token="unlocked")
        self.assertEqual(h.manager.current().access_token, "unlocked")
        h.manager.current()
        self.assertEqual(h.keychain_loads, 2)

    def test_missing_credentials_is_a_401(self):
        h = Harness(self.tmp.name)
        with self.assertRaises(AntigravityError) as raised:
            h.manager.current()
        self.assertEqual(raised.exception.status, 401)

    def test_store_follows_profile_switch(self):
        stores = {"a": CredentialStore(Path(self.tmp.name) / "a.json"), "b": CredentialStore(Path(self.tmp.name) / "b.json")}
        stores["a"].save(Credentials.from_mapping(fresh(access_token="A"), source=SOURCE_BROWSER))
        stores["b"].save(Credentials.from_mapping(fresh(access_token="B"), source=SOURCE_BROWSER))
        active = ["a"]
        manager = CredentialManager(store_factory=lambda: stores[active[0]], keychain_loader=lambda: None)
        self.assertEqual(manager.current().access_token, "A")
        active[0] = "b"
        self.assertEqual(manager.current().access_token, "B")


class RefreshAfterRejectionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def test_rejected_browser_token_is_refreshed_and_saved(self):
        h = Harness(self.tmp.name)
        h.store.save(Credentials.from_mapping(fresh(), source=SOURCE_BROWSER))
        refreshed = h.manager.refresh(h.manager.current())
        self.assertEqual(refreshed.access_token, "new-1")
        self.assertEqual(h.store.load().access_token, "new-1")

    def test_token_refreshed_by_another_process_is_reused(self):
        h = Harness(self.tmp.name)
        h.store.save(Credentials.from_mapping(fresh(), source=SOURCE_BROWSER))
        rejected = h.manager.current()
        h.store.save(Credentials.from_mapping(fresh(access_token="from-other-process"), source=SOURCE_BROWSER))
        self.assertEqual(h.manager.refresh(rejected).access_token, "from-other-process")
        self.assertEqual(h.refreshes, [])

    def test_rejected_keychain_token_updates_process_cache(self):
        h = Harness(self.tmp.name, keychain=fresh())
        h.manager.refresh(h.manager.current())
        self.assertEqual(h.manager.current().access_token, "new-1")

    def test_logout_during_request_does_not_bring_browser_login_back(self):
        h = Harness(self.tmp.name, keychain=fresh(access_token="keychain"))
        h.store.save(Credentials.from_mapping(fresh(access_token="browser"), source=SOURCE_BROWSER))
        rejected = h.manager.current()
        h.manager.logout()
        self.assertEqual(h.manager.refresh(rejected).access_token, "keychain")
        self.assertIsNone(h.store.load())
        self.assertEqual(h.refreshes, [])

    def test_keychain_token_refreshed_by_another_request_is_reused(self):
        h = Harness(self.tmp.name, keychain=fresh())
        stale = h.manager.current()
        h.manager.refresh(stale)
        h.manager.refresh(stale)
        self.assertEqual(len(h.refreshes), 1)

    def test_without_refresh_token_stays_expired(self):
        h = Harness(self.tmp.name)
        with self.assertRaises(TokenExpired):
            h.manager.refresh(Credentials(access_token="a", source=SOURCE_BROWSER))


class LoginTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def test_login_prefers_keychain_and_removes_browser_override(self):
        h = Harness(self.tmp.name, keychain=fresh(project_id=""))
        h.store.save(Credentials.from_mapping(fresh(access_token="browser"), source=SOURCE_BROWSER))
        with patch.object(oauth, "browser_login", side_effect=AssertionError("browser flow must not run")):
            creds = h.manager.login(open_browser=False)
        self.assertEqual((creds.source, creds.project_id, creds.email), (SOURCE_KEYCHAIN, "discovered", "user@example.com"))
        self.assertIsNone(h.store.load())
        self.assertEqual(h.manager.current().access_token, "tok")

    def test_no_keychain_login_saves_browser_credentials(self):
        h = Harness(self.tmp.name, keychain=fresh())
        tokens = {"access_token": "browser", "refresh_token": "b-ref", "expires_at": time.time() + 3600}
        with patch.object(oauth, "browser_login", return_value=tokens):
            creds = h.manager.login(use_keychain=False, open_browser=False)
        saved = h.store.load()
        self.assertEqual((creds.access_token, saved.access_token, saved.project_id, saved.email),
                         ("browser", "browser", "discovered", "user@example.com"))

    def test_describe_makes_no_network_calls(self):
        h = Harness(self.tmp.name, keychain={"refresh_token": "ref"})
        status = h.manager.describe()
        self.assertEqual(status["source"], "agy Keychain")
        self.assertFalse(status["has_access_token"])
        self.assertEqual((h.refreshes, h.projects), ([], []))


if __name__ == "__main__":
    unittest.main()
