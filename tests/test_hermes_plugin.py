import re
import sys
import tempfile
import types
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import antigravity_provider
import antigravity_provider.hermes_plugin as plugin
from antigravity_provider.catalog import build_catalog, fallback_catalog

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


class SelectModelTests(unittest.TestCase):
    ACCOUNT = build_catalog({"models": {"gemini-3-flash": {}, "claude-sonnet-4-6": {}}, "defaultAgentModelId": "claude-sonnet-4-6"})

    def select(self, model, catalog):
        saved = []
        config = types.ModuleType("hermes_cli.config")
        config.load_config = lambda: {}
        config.save_config = saved.append
        service = SimpleNamespace(catalog=lambda: catalog)
        with patch.dict(sys.modules, {"hermes_cli": types.ModuleType("hermes_cli"), "hermes_cli.config": config}), \
                patch.object(plugin, "default_service", return_value=service), patch("builtins.print"):
            plugin._select_model(model)
        return saved[0]["model"]["default"]

    def test_model_the_account_lists_is_saved(self):
        self.assertEqual(self.select("gemini-3-flash", self.ACCOUNT), "gemini-3-flash")

    def test_model_the_account_lacks_is_refused(self):
        with self.assertRaisesRegex(SystemExit, "gemini-3-flash"):  # the message lists what is available
            self.select("gemini-3.1-pro", self.ACCOUNT)

    def test_no_model_uses_the_account_default(self):
        self.assertEqual(self.select(None, self.ACCOUNT), "google-antigravity/claude-sonnet-4-6")

    def test_no_model_without_the_account_list_is_refused(self):
        # Discovery failed: the built-in list is not the account's, so its default may not exist.
        with self.assertRaises(SystemExit):
            self.select(None, fallback_catalog())


if __name__ == "__main__":
    unittest.main()
