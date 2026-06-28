import unittest

from ag_proxy.models import KNOWN_MODELS, clamp_reasoning_effort, normalize_model_id, resolve_wire_model_id


class ModelCatalogTests(unittest.TestCase):
    def test_normalizes_bare_model(self):
        self.assertEqual(normalize_model_id("gemini-3.1-pro"), "google-antigravity/gemini-3.1-pro")

    def test_routes_pro_high_to_working_agent_wire_id(self):
        self.assertEqual(resolve_wire_model_id("google-antigravity/gemini-3.1-pro", "high"), "gemini-pro-agent")

    def test_clamps_gemini_pro_to_low_high(self):
        self.assertEqual(clamp_reasoning_effort("google-antigravity/gemini-3.1-pro", "minimal"), "low")
        self.assertEqual(clamp_reasoning_effort("google-antigravity/gemini-3.1-pro", "medium"), "low")
        self.assertEqual(clamp_reasoning_effort("google-antigravity/gemini-3.1-pro", "xhigh"), "high")

    def test_clamps_gemini_flash_to_low_medium_high(self):
        self.assertEqual(resolve_wire_model_id("google-antigravity/gemini-3.5-flash", "minimal"), "gemini-3.5-flash-extra-low")
        self.assertEqual(resolve_wire_model_id("google-antigravity/gemini-3.5-flash", "medium"), "gemini-3.5-flash-low")
        self.assertEqual(resolve_wire_model_id("google-antigravity/gemini-3.5-flash", "xhigh"), "gemini-3-flash-agent")

    def test_includes_gpt_oss_120b_medium(self):
        self.assertIn("google-antigravity/gpt-oss-120b", KNOWN_MODELS)
        self.assertEqual(clamp_reasoning_effort("google-antigravity/gpt-oss-120b", "high"), "medium")
        self.assertEqual(resolve_wire_model_id("google-antigravity/gpt-oss-120b", "high"), "openai/gpt-oss-120b-maas")


if __name__ == "__main__":
    unittest.main()
