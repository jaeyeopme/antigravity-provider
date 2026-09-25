import unittest

from antigravity_provider.models import DEFAULT_MODEL, normalize_effort, normalize_model_id


class ModelTests(unittest.TestCase):
    def test_default_model_is_stable_fallback_not_latest_rollout(self):
        self.assertEqual(DEFAULT_MODEL, "google-antigravity/gemini-3.1-pro")

    def test_normalizes_bare_model(self):
        self.assertEqual(normalize_model_id("gemini-3.8-flash"), "google-antigravity/gemini-3.8-flash")
        self.assertEqual(normalize_model_id("gemini-3.1-pro"), "google-antigravity/gemini-3.1-pro")

    def test_normalizes_reasoning_aliases_without_model_specific_hardcoding(self):
        self.assertEqual(normalize_effort("minimum"), "minimal")
        self.assertEqual(normalize_effort("normal"), "medium")
        self.assertEqual(normalize_effort("xhigh"), "high")
        self.assertEqual(normalize_effort("disabled"), "off")


if __name__ == "__main__":
    unittest.main()
