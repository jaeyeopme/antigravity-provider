import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from antigravity_provider import cloudcode
from antigravity_provider.cloudcode import (
    PROJECT_ONBOARD_INTERVAL_SECONDS,
    ClientVersion,
    antigravity_user_agent,
    fetch_released_version,
    load_or_onboard_project,
    read_default_tier,
    read_project_id,
)
from antigravity_provider.errors import AntigravityError


class CloudCodeTests(unittest.TestCase):
    def test_project_id_string_or_object(self):
        self.assertEqual(read_project_id("p1"), "p1")
        self.assertEqual(read_project_id({"id": "p2"}), "p2")
        self.assertIsNone(read_project_id({}))

    def test_default_tier(self):
        self.assertEqual(
            read_default_tier([{"id": "free"}, {"id": "pro", "isDefault": True}]), "pro"
        )
        self.assertEqual(read_default_tier([]), "legacy-tier")

    def test_onboards_when_no_project(self):
        calls = []

        def fake_post(url, body, headers):
            calls.append((url, body))
            if url.endswith("loadCodeAssist"):
                return {"allowedTiers": [{"id": "pro", "isDefault": True}]}
            return {"done": True, "response": {"cloudaicompanionProject": {"id": "p3"}}}

        self.assertEqual(
            load_or_onboard_project("tok", post_json=fake_post, sleep=lambda _: None), "p3"
        )
        self.assertTrue(calls[1][0].endswith("onboardUser"))

    def test_onboarding_waits_for_the_operation_to_finish(self):
        answers = iter(
            [
                {},
                {"done": False},
                {"done": False},
                {"done": True, "response": {"cloudaicompanionProject": "p4"}},
            ]
        )
        sleeps = []
        project = load_or_onboard_project(
            "tok", post_json=lambda url, body, headers: next(answers), sleep=sleeps.append
        )
        self.assertEqual(project, "p4")
        self.assertEqual(sleeps, [PROJECT_ONBOARD_INTERVAL_SECONDS] * 2)

    def test_onboarding_that_never_finishes_is_an_error(self):
        with self.assertRaisesRegex(AntigravityError, "project id"):
            load_or_onboard_project(
                "tok", post_json=lambda url, body, headers: {"done": False}, sleep=lambda _: None
            )


def unreachable():
    raise AntigravityError("update server unreachable", status=502)


def answering(*answers):
    """A lookup that gives one answer per call; an exception answer is raised."""
    remaining = iter(answers)

    def fetch():
        answer = next(remaining)
        if isinstance(answer, Exception):
            raise answer
        return answer

    return fetch


class ClientVersionTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.path = Path(directory.name) / "client_version.json"
        # Older than every version below, so a test can tell the saved version from the built-in.
        built_in = patch.object(cloudcode, "DEFAULT_CLIENT_VERSION", "2.30.0")
        built_in.start()
        self.addCleanup(built_in.stop)

    def test_presents_the_version_the_update_server_reports(self):
        version = ClientVersion(fetch=lambda: "2.34.0", path=self.path)
        self.assertEqual(version.get(), "2.34.0")

    def test_keeps_one_version_for_the_whole_process(self):
        version = ClientVersion(fetch=answering("2.34.0", "2.35.0"), path=self.path)
        self.assertEqual([version.get(), version.get()], ["2.34.0", "2.34.0"])

    def test_falls_back_to_the_version_an_earlier_process_saved(self):
        ClientVersion(fetch=lambda: "2.34.0", path=self.path).get()
        self.assertEqual(ClientVersion(fetch=unreachable, path=self.path).get(), "2.34.0")

    def test_keeps_the_saved_version_for_the_rest_of_the_process(self):
        ClientVersion(fetch=lambda: "2.34.0", path=self.path).get()
        version = ClientVersion(fetch=answering(AntigravityError("down"), "2.35.0"), path=self.path)
        self.assertEqual([version.get(), version.get()], ["2.34.0", "2.34.0"])

    def test_presents_the_built_in_version_when_none_was_ever_read(self):
        version = ClientVersion(fetch=unreachable, path=self.path)
        self.assertEqual(version.get(), "2.30.0")

    def test_presents_the_built_in_version_when_the_saved_one_is_older(self):
        ClientVersion(fetch=lambda: "2.9.0", path=self.path).get()  # 2.9 is older than 2.30
        self.assertEqual(ClientVersion(fetch=unreachable, path=self.path).get(), "2.30.0")

    def test_ignores_a_saved_file_that_does_not_hold_a_version(self):
        self.path.write_text('{"version": "9.9.9\\r\\nX-Injected: 1"}', encoding="utf-8")
        version = ClientVersion(fetch=unreachable, path=self.path)
        self.assertEqual(version.get(), "2.30.0")

    def test_uses_the_reported_version_when_it_cannot_be_saved(self):
        with tempfile.NamedTemporaryFile() as not_a_directory:
            path = Path(not_a_directory.name) / "client_version.json"
            self.assertEqual(ClientVersion(fetch=lambda: "2.34.0", path=path).get(), "2.34.0")


class Manifest:
    """The update server's response."""

    def __init__(self, body):
        self.body = body

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self, amount):
        return self.body[:amount]


class ReleasedVersionTests(unittest.TestCase):
    def fetch(self, answer):
        def fake_urlopen(request, timeout):
            self.assertEqual(request.get_header("User-agent"), "electron-builder")
            if isinstance(answer, Exception):
                raise answer
            return Manifest(answer)

        with patch("antigravity_provider.cloudcode.urllib.request.urlopen", fake_urlopen):
            return fetch_released_version()

    def test_reads_the_version_the_update_manifest_names(self):
        manifest = (
            b"version: 2.34.0\n"
            b"files:\n"
            b"  - url: https://example.invalid/2.34.0-1/darwin-arm/Antigravity.zip\n"
            b"    sha512: 4mY3QkbpWxuru5gPvJrabdr3tMH\n"
        )
        self.assertEqual(self.fetch(manifest), "2.34.0")
        self.assertEqual(self.fetch(b'version: "2.34.0"\n'), "2.34.0")  # YAML may quote it

    def test_a_response_that_names_no_version_is_an_error(self):
        with self.assertRaisesRegex(AntigravityError, "no version"):
            self.fetch(b"<html>Service Unavailable</html>")

    def test_an_unreachable_update_server_is_an_error(self):
        with self.assertRaisesRegex(AntigravityError, "connection refused"):
            self.fetch(OSError("connection refused"))


class UserAgentTests(unittest.TestCase):
    def setUp(self):
        environment = patch.dict("os.environ")  # restores what the pops below remove
        environment.start()
        self.addCleanup(environment.stop)
        for name in ("ANTIGRAVITY_CLIENT_VERSION", "PI_AI_ANTIGRAVITY_VERSION"):
            os.environ.pop(name, None)
        released = patch.object(cloudcode.client_version, "get", return_value="2.34.0")
        released.start()
        self.addCleanup(released.stop)

    def test_presents_the_released_version_as_the_build_for_the_host_os(self):
        # The OS alone picks the build; the host's architecture is not read.
        for system, build in (
            ("Darwin", "os_type=darwin; arch=arm64"),
            ("Linux", "os_type=linux; arch=amd64"),
            ("Windows", "os_type=windows; arch=amd64"),
            ("FreeBSD", "os_type=linux; arch=amd64"),
        ):
            with patch("platform.system", return_value=system):
                self.assertEqual(
                    antigravity_user_agent(),
                    f"antigravity/hub/2.34.0 (aidev_client; {build}; cl=1005016104)",
                )

    def test_the_environment_names_the_version_instead(self):
        with patch.dict("os.environ", {"PI_AI_ANTIGRAVITY_VERSION": "2.39.0"}):
            self.assertIn("antigravity/hub/2.39.0 ", antigravity_user_agent())
            with patch.dict("os.environ", {"ANTIGRAVITY_CLIENT_VERSION": "2.40.0"}):
                self.assertIn("antigravity/hub/2.40.0 ", antigravity_user_agent())


if __name__ == "__main__":
    unittest.main()
