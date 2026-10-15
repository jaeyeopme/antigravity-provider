import os
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch

from antigravity_provider import paths


def fake_hermes_constants(home, override=None):
    module = types.ModuleType("hermes_constants")
    module.get_hermes_home = lambda: Path(home)
    module.get_hermes_home_override = lambda: override
    return module


def without_hermes_home_env():
    env = {key: value for key, value in os.environ.items() if key != "HERMES_HOME"}
    return patch.dict(os.environ, env, clear=True)


class PathTests(unittest.TestCase):
    def test_uses_hermes_home_resolution_when_available(self):
        with tempfile.TemporaryDirectory() as hermes, tempfile.TemporaryDirectory() as env:
            with patch.dict(sys.modules, {"hermes_constants": fake_hermes_constants(hermes)}), \
                    patch.dict(os.environ, {"HERMES_HOME": env}):
                self.assertEqual(paths.hermes_home(), Path(hermes))
                self.assertEqual(paths.model_cache_path(), Path(hermes) / ".antigravity_models.json")

    def test_login_saved_under_home_dir_by_earlier_version_is_still_found(self):
        # e.g. Windows: Hermes uses %LOCALAPPDATA%/hermes, versions before 2026.10.15 used ~/.hermes.
        with tempfile.TemporaryDirectory() as platform_home, tempfile.TemporaryDirectory() as user_home:
            legacy = Path(user_home) / ".hermes" / ".antigravity_oauth.json"
            legacy.parent.mkdir()
            legacy.write_text("{}")
            with patch.dict(sys.modules, {"hermes_constants": fake_hermes_constants(platform_home)}), \
                    without_hermes_home_env(), patch.object(Path, "home", return_value=Path(user_home)):
                self.assertEqual(paths.oauth_credentials_path(), legacy)
                (Path(platform_home) / ".antigravity_oauth.json").write_text("{}")
                self.assertEqual(paths.oauth_credentials_path(), Path(platform_home) / ".antigravity_oauth.json")

    def test_profile_never_falls_back_to_default_profile_login(self):
        with tempfile.TemporaryDirectory() as profile, tempfile.TemporaryDirectory() as user_home:
            default_login = Path(user_home) / ".hermes" / ".antigravity_oauth.json"
            default_login.parent.mkdir()
            default_login.write_text("{}")
            constants = fake_hermes_constants(profile, override=profile)
            with patch.dict(sys.modules, {"hermes_constants": constants}), \
                    without_hermes_home_env(), patch.object(Path, "home", return_value=Path(user_home)):
                self.assertEqual(paths.oauth_credentials_path(), Path(profile) / ".antigravity_oauth.json")

if __name__ == "__main__":
    unittest.main()
