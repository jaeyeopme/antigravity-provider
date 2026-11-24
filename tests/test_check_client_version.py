import datetime
import importlib.util
import unittest
from pathlib import Path
from unittest.mock import patch

from antigravity_provider import cloudcode

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "check_client_version.py"
spec = importlib.util.spec_from_file_location("check_client_version", SCRIPT)
assert spec is not None and spec.loader is not None
check = importlib.util.module_from_spec(spec)
spec.loader.exec_module(check)


class CheckClientVersionTests(unittest.TestCase):
    def setUp(self):
        for name, value in (
            ("DEFAULT_CLIENT_VERSION", "2.30.0"),
            ("DEFAULT_CLIENT_VERSION_SET", "2026-01-01"),
            ("CLIENT_VERSION_MAX_AGE_DAYS", 30),
        ):
            patcher = patch.object(cloudcode, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)

    def test_the_built_in_version_is_fine_while_it_is_the_newest(self):
        self.assertIsNone(check.problem("2.30.0", datetime.date(2027, 1, 1)))

    def test_an_older_version_on_the_server_is_fine(self):
        self.assertIsNone(check.problem("2.9.0", datetime.date(2027, 1, 1)))

    def test_a_newer_version_is_fine_while_the_built_in_one_is_recent(self):
        self.assertIsNone(check.problem("2.31.0", datetime.date(2026, 1, 31)))

    def test_a_newer_version_and_an_old_built_in_one_need_a_raise(self):
        found = check.problem("2.31.0", datetime.date(2026, 2, 1))
        self.assertIn('DEFAULT_CLIENT_VERSION = "2.31.0"', found)
        self.assertIn('DEFAULT_CLIENT_VERSION_SET = "2026-02-01"', found)

    def test_the_set_date_is_a_date(self):
        datetime.date.fromisoformat(cloudcode.DEFAULT_CLIENT_VERSION_SET)


if __name__ == "__main__":
    unittest.main()
