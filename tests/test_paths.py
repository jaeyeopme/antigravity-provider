import os
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch

from antigravity_provider import paths


def fake_hermes_constants(home):
    module = types.ModuleType("hermes_constants")
    module.get_hermes_home = lambda: Path(home)
    return module


class PathTests(unittest.TestCase):
    def test_uses_hermes_home_resolution_when_available(self):
        with tempfile.TemporaryDirectory() as hermes, tempfile.TemporaryDirectory() as env:
            with patch.dict(sys.modules, {"hermes_constants": fake_hermes_constants(hermes)}), \
                    patch.dict(os.environ, {"HERMES_HOME": env}):
                self.assertEqual(paths.hermes_home(), Path(hermes))
                self.assertEqual(paths.model_cache_path(), Path(hermes) / ".antigravity_models.json")

    def test_login_saved_by_earlier_version_is_still_found(self):
        with tempfile.TemporaryDirectory() as hermes, tempfile.TemporaryDirectory() as legacy:
            (Path(legacy) / ".antigravity_oauth.json").write_text("{}")
            with patch.dict(sys.modules, {"hermes_constants": fake_hermes_constants(hermes)}), \
                    patch.dict(os.environ, {"HERMES_HOME": legacy}):
                self.assertEqual(paths.oauth_credentials_path(), Path(legacy) / ".antigravity_oauth.json")
                (Path(hermes) / ".antigravity_oauth.json").write_text("{}")
                self.assertEqual(paths.oauth_credentials_path(), Path(hermes) / ".antigravity_oauth.json")


if __name__ == "__main__":
    unittest.main()
