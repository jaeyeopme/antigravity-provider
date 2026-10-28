import base64
import getpass
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from antigravity_provider.credentials import (
    SOURCE_BROWSER,
    SOURCE_KEYCHAIN,
    Credentials,
    CredentialStore,
    load_agy_keychain_credentials,
    parse_agy_keychain_secret,
)


class CredentialsTests(unittest.TestCase):
    def test_legacy_key_spellings_are_normalized(self):
        creds = Credentials.from_mapping(
            {"access": "a", "refresh": "r", "expires": 123, "projectId": "p"}, source=SOURCE_BROWSER
        )
        self.assertEqual(
            (creds.access_token, creds.refresh_token, creds.expires_at, creds.project_id),
            ("a", "r", 123.0, "p"),
        )

    def test_needs_refresh(self):
        now = 1000.0
        self.assertFalse(
            Credentials(access_token="a", refresh_token="r", expires_at=now + 3600).needs_refresh(
                now
            )
        )
        self.assertTrue(
            Credentials(access_token="a", refresh_token="r", expires_at=now + 30).needs_refresh(now)
        )
        self.assertTrue(Credentials(refresh_token="r").needs_refresh(now))
        self.assertFalse(Credentials(access_token="a", expires_at=now - 1).needs_refresh(now))

    def test_with_tokens_keeps_refresh_token_when_not_rotated(self):
        creds = Credentials(access_token="old", refresh_token="r", project_id="p")
        updated = creds.with_tokens({"access_token": "new", "expires_at": 5})
        self.assertEqual(
            (updated.access_token, updated.refresh_token, updated.project_id), ("new", "r", "p")
        )


class CredentialStoreTests(unittest.TestCase):
    def assertPrivate(self, path):
        if os.name != "nt":
            self.assertEqual(os.stat(path).st_mode & 0o777, 0o600)
            return
        # Windows ignores chmod; only the file's ACL decides who can read it.
        listing = subprocess.run(
            ["icacls", str(path)], capture_output=True, text=True, check=True
        ).stdout
        # Lines read "<path> DOMAIN\\user:(F)" then "<indent>BUILTIN\\Administrators:(I)(F)".
        entries = [
            line[: line.index(":(")].rsplit(" ", 1)[-1]
            for line in listing.splitlines()
            if ":(" in line
        ]
        self.assertEqual(len(entries), 1, listing)
        self.assertTrue(entries[0].lower().endswith(getpass.getuser().lower()), listing)

    def test_round_trip_credentials(self):
        with tempfile.TemporaryDirectory() as d:
            # The file's folder is the Hermes home, which may be shared on purpose: leave its mode alone.
            os.chmod(d, 0o755)
            store = CredentialStore(Path(d) / "credentials.json")
            store.save(
                Credentials(access_token="a", refresh_token="r", project_id="p", expires_at=123)
            )
            loaded = store.load()
            self.assertEqual(loaded.project_id, "p")
            self.assertEqual(loaded.source, SOURCE_BROWSER)
            if os.name != "nt":
                self.assertEqual(os.stat(d).st_mode & 0o777, 0o755)
            self.assertPrivate(store.path)
            self.assertNotIn("source", json.loads(store.path.read_text()))
            store.delete()
            self.assertIsNone(store.load())

    def test_reads_files_written_by_earlier_versions(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "credentials.json"
            path.write_text(
                json.dumps(
                    {"access_token": "a", "refresh_token": "r", "expires_at": 1, "project_id": "p"}
                )
            )
            self.assertEqual(CredentialStore(path).load().refresh_token, "r")

    def test_default_path_is_profile_scoped(self):
        with tempfile.TemporaryDirectory() as d, patch.dict(os.environ, {"HERMES_HOME": d}):
            self.assertEqual(CredentialStore.default().path, Path(d) / ".antigravity_oauth.json")


class KeychainTests(unittest.TestCase):
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
        self.assertEqual(parsed.source, SOURCE_KEYCHAIN)
        self.assertEqual((parsed.access_token, parsed.refresh_token), ("a", "r"))
        self.assertIsInstance(parsed.expires_at, float)

    def test_reads_the_agy_item_with_the_security_tool_on_macos(self):
        secret = json.dumps({"token": {"access_token": "a", "refresh_token": "r"}}).encode()
        with (
            patch.object(sys, "platform", "darwin"),
            patch(
                "antigravity_provider.credentials.subprocess.check_output", return_value=secret
            ) as run,
        ):
            creds = load_agy_keychain_credentials()
        self.assertEqual((creds.access_token, creds.refresh_token), ("a", "r"))
        self.assertEqual(
            run.call_args.args[0],
            ["security", "find-generic-password", "-a", "antigravity", "-s", "gemini", "-w"],
        )

    def test_no_keychain_outside_macos(self):
        with (
            patch.object(sys, "platform", "linux"),
            patch("antigravity_provider.credentials.subprocess.check_output") as run,
        ):
            self.assertIsNone(load_agy_keychain_credentials())
        run.assert_not_called()

    def test_unreadable_keychain_is_no_credential(self):
        self.assertIsNone(load_agy_keychain_credentials(runner=lambda: "not-json"))


if __name__ == "__main__":
    unittest.main()
