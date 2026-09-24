import unittest

from antigravity_provider.models import (
    DEFAULT_MODEL,
    KNOWN_MODELS,
    clamp_reasoning_effort,
    normalize_model_id,
    resolve_wire_model_id,
)


class ModelCatalogTests(unittest.TestCase):
    def test_default_model_is_gemini_38_flash(self):
        self.assertEqual(DEFAULT_MODEL, "google-antigravity/gemini-3.8-flash")

    def test_normalizes_bare_model(self):
        self.assertEqual(normalize_model_id("gemini-3.8-flash"), "google-antigravity/gemini-3.8-flash")
        self.assertEqual(normalize_model_id("gemini-3.1-pro"), "google-antigravity/gemini-3.1-pro")

    def test_routes_pro_high_to_working_agent_wire_id(self):
        self.assertEqual(resolve_wire_model_id("google-antigravity/gemini-3.1-pro", "high"), "gemini-pro-agent")

    def test_clamps_gemini_pro_to_low_high(self):
        self.assertEqual(clamp_reasoning_effort("google-antigravity/gemini-3.1-pro", "minimal"), "low")
        self.assertEqual(clamp_reasoning_effort("google-antigravity/gemini-3.1-pro", "medium"), "low")
        self.assertEqual(clamp_reasoning_effort("google-antigravity/gemini-3.1-pro", "xhigh"), "high")

    def test_clamps_gemini_38_flash_to_low_medium_high(self):
        self.assertEqual(resolve_wire_model_id("google-antigravity/gemini-3.8-flash", "minimal"), "gemini-3.8-flash-low")
        self.assertEqual(resolve_wire_model_id("google-antigravity/gemini-3.8-flash", "medium"), "gemini-3.8-flash-medium")
        self.assertEqual(resolve_wire_model_id("google-antigravity/gemini-3.8-flash", "high"), "gemini-3.8-flash-high")

    def test_clamps_gemini_37_flash_to_low_medium_high(self):
        self.assertEqual(resolve_wire_model_id("google-antigravity/gemini-3.7-flash", "minimal"), "gemini-3.7-flash-low")
        self.assertEqual(resolve_wire_model_id("google-antigravity/gemini-3.7-flash", "medium"), "gemini-3.7-flash-medium")
        self.assertEqual(resolve_wire_model_id("google-antigravity/gemini-3.7-flash", "high"), "gemini-3.7-flash-high")

    def test_clamps_gemini_36_flash_to_low_medium_high(self):
        self.assertEqual(resolve_wire_model_id("google-antigravity/gemini-3.6-flash", "minimal"), "gemini-3.6-flash-low")
        self.assertEqual(resolve_wire_model_id("google-antigravity/gemini-3.6-flash", "medium"), "gemini-3.6-flash-medium")
        self.assertEqual(resolve_wire_model_id("google-antigravity/gemini-3.6-flash", "high"), "gemini-3.6-flash-high")

    def test_clamps_gemini_legacy_flash_to_low_medium_high(self):
        self.assertEqual(resolve_wire_model_id("google-antigravity/gemini-3.5-flash", "minimal"), "gemini-3.5-flash-extra-low")
        self.assertEqual(resolve_wire_model_id("google-antigravity/gemini-3.5-flash", "medium"), "gemini-3.5-flash-low")
        self.assertEqual(resolve_wire_model_id("google-antigravity/gemini-3.5-flash", "xhigh"), "gemini-3-flash-agent")

    def test_routes_claude_models(self):
        self.assertEqual(resolve_wire_model_id("google-antigravity/claude-sonnet-4-6"), "claude-sonnet-4-6")
        self.assertEqual(resolve_wire_model_id("google-antigravity/claude-opus-4-6"), "claude-opus-4-6-thinking")

    def test_includes_gpt_oss_120b_medium(self):
        self.assertIn("google-antigravity/gpt-oss-120b", KNOWN_MODELS)
        self.assertEqual(clamp_reasoning_effort("google-antigravity/gpt-oss-120b", "high"), "medium")
        self.assertEqual(resolve_wire_model_id("google-antigravity/gpt-oss-120b", "high"), "gpt-oss-120b-medium")

    def test_known_models_catalog(self):
        expected_models = [
            "google-antigravity/gemini-3.8-flash",
            "google-antigravity/gemini-3.7-flash",
            "google-antigravity/gemini-3.6-flash",
            "google-antigravity/gemini-3.1-pro",
            "google-antigravity/claude-sonnet-4-6",
            "google-antigravity/claude-opus-4-6",
            "google-antigravity/gpt-oss-120b",
            "google-antigravity/gemini-3.5-flash",
        ]
        for m in expected_models:
            self.assertIn(m, KNOWN_MODELS)


if __name__ == "__main__":
    unittest.main()
