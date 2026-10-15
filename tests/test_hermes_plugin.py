import re
import tempfile
import unittest
from pathlib import Path

import antigravity_provider
import antigravity_provider.hermes_plugin as plugin

ROOT = Path(__file__).resolve().parents[1]


class FakeCtx:
    def __init__(self):
        self.cli = {}
        self.middleware = []

    def register_cli_command(self, **kwargs):
        self.cli[kwargs["name"]] = kwargs

    def register_middleware(self, kind, callback):
        self.middleware.append((kind, callback))


class HermesPluginTests(unittest.TestCase):
    def test_register_adds_cli_and_session_request_middleware(self):
        ctx = FakeCtx()
        plugin.register(ctx)
        self.assertIn("agy", ctx.cli)
        self.assertEqual(ctx.middleware[0][0], "llm_request")

    def test_request_middleware_passthrough_for_other_provider(self):
        request = {"model": "x"}
        out = plugin.antigravity_llm_request(provider="openai", request=request, session_id="s")
        self.assertEqual(out, {"request": request})

    def test_request_middleware_injects_real_session_id(self):
        out = plugin.antigravity_llm_request(provider="antigravity", request={"model": "m"}, session_id="hermes-session")
        self.assertEqual(out["request"]["_antigravity_session_id"], "hermes-session")

    def test_ensure_provider_profile_files(self):
        with tempfile.TemporaryDirectory() as td:
            path = plugin.ensure_provider_profile_files(Path(td))
            init = (path / "__init__.py").read_text()
            # Existing installs import exactly this; it must stay stable across releases.
            self.assertIn("from antigravity_provider.hermes_provider import register_provider_profile", init)
            self.assertIn(f"version: {antigravity_provider.__version__}", (path / "plugin.yaml").read_text())


class VersionTests(unittest.TestCase):
    def test_plugin_manifest_matches_package_version(self):
        manifest = (ROOT / "plugin.yaml").read_text()
        self.assertEqual(re.search(r"^version: (.+)$", manifest, re.M).group(1), antigravity_provider.__version__)

    def test_changelog_has_entry_for_current_version(self):
        self.assertIn(f"## {antigravity_provider.__version__}", (ROOT / "CHANGELOG.md").read_text())


if __name__ == "__main__":
    unittest.main()
