import tempfile
import time
import unittest
from pathlib import Path

from antigravity_provider.catalog import CatalogManager, build_catalog


CATALOG_PAYLOAD = {
    "models": {
        "gemini-3.8-flash-tiered": {
            "displayName": "Gemini 3.8 Flash",
            "model": "MODEL_PLACEHOLDER_M322",
            "maxOutputTokens": 65536,
            "supportsThinking": True,
            "thinkingBudget": -1,
        },
        "gemini-3.9-flash-low": {
            "displayName": "Gemini 3.9 Flash (Low)",
            "model": "MODEL_39_LOW",
            "maxOutputTokens": 32000,
            "supportsThinking": True,
            "thinkingBudget": 1000,
        },
        "gemini-3.9-flash-medium": {
            "displayName": "Gemini 3.9 Flash (Medium)",
            "model": "MODEL_39_MEDIUM",
            "maxOutputTokens": 32000,
            "supportsThinking": True,
            "thinkingBudget": 4000,
        },
        "gemini-3.9-flash-high": {
            "displayName": "Gemini 3.9 Flash (High)",
            "model": "MODEL_39_HIGH",
            "maxOutputTokens": 32000,
            "supportsThinking": True,
            "thinkingBudget": -1,
        },
        "new-family-agent": {
            "displayName": "New Family",
            "model": "MODEL_NEW",
            "maxOutputTokens": 8192,
            "supportsThinking": False,
        },
        "internal-image-model": {"displayName": "Image", "isInternal": True},
    },
    "agentModelSorts": {
        "gemini-3.9-flash-low": 1,
        "gemini-3.9-flash-medium": 2,
        "gemini-3.9-flash-high": 3,
        "new-family-agent": 4,
    },
    "tieredModelIds": {"flash": ["gemini-3.8-flash-tiered"]},
    "defaultAgentModelId": "gemini-3.9-flash-high",
}


class CatalogTests(unittest.TestCase):
    def test_unknown_thinking_family_is_grouped_without_static_entry(self):
        catalog = build_catalog(CATALOG_PAYLOAD)
        self.assertIn("google-antigravity/gemini-3.9-flash", catalog.model_ids())
        route = catalog.resolve("google-antigravity/gemini-3.9-flash", "high")
        self.assertEqual(route.wire_model, "gemini-3.9-flash-high")
        self.assertEqual(route.model_enum, "MODEL_39_HIGH")
        self.assertEqual(route.thinking_budget, -1)
        self.assertEqual(route.max_output_tokens, 32000)

    def test_tiered_model_uses_one_live_wire_profile_for_every_effort(self):
        catalog = build_catalog(CATALOG_PAYLOAD)
        for effort, budget in (("low", 1000), ("medium", 4000), ("high", -1)):
            route = catalog.resolve("google-antigravity/gemini-3.8-flash", effort)
            self.assertEqual(route.wire_model, "gemini-3.8-flash-tiered")
            self.assertEqual(route.model_enum, "MODEL_PLACEHOLDER_M322")
            self.assertEqual(route.thinking_budget, budget)

    def test_backend_selected_unknown_singleton_remains_available(self):
        catalog = build_catalog(CATALOG_PAYLOAD)
        self.assertIn("google-antigravity/new-family-agent", catalog.model_ids())
        route = catalog.resolve("new-family-agent", "high")
        self.assertEqual(route.wire_model, "new-family-agent")
        self.assertIsNone(route.thinking_budget)

    def test_backend_default_is_normalized_without_changing_existing_config(self):
        catalog = build_catalog(CATALOG_PAYLOAD)
        self.assertEqual(catalog.default_model, "google-antigravity/gemini-3.9-flash")

    def test_advertised_variants_beat_stale_unadvertised_tiered_route(self):
        payload = {
            "models": {
                "gemini-3.6-flash-tiered": {
                    "model": "MODEL_TIERED",
                    "supportsThinking": True,
                    "thinkingBudget": -1,
                },
                "gemini-3.6-flash-low": {
                    "model": "MODEL_LOW",
                    "supportsThinking": True,
                    "thinkingBudget": 1000,
                },
                "gemini-3.6-flash-high": {
                    "model": "MODEL_HIGH",
                    "supportsThinking": True,
                    "thinkingBudget": -1,
                },
            },
            "agentModelSorts": {
                "gemini-3.6-flash-low": 1,
                "gemini-3.6-flash-high": 2,
            },
        }
        route = build_catalog(payload).resolve("gemini-3.6-flash", "high")
        self.assertEqual(route.wire_model, "gemini-3.6-flash-high")
        self.assertEqual(route.model_enum, "MODEL_HIGH")

    def test_expired_last_known_good_survives_refresh_failure(self):
        class Client:
            def __init__(self):
                self.fail = False

            def fetch_available_models(self, *, access_token, project_id):
                if self.fail:
                    raise RuntimeError("offline")
                return CATALOG_PAYLOAD

        with tempfile.TemporaryDirectory() as directory:
            now = [1000.0]
            client = Client()
            manager = CatalogManager(
                path=Path(directory) / "catalog.json",
                ttl_seconds=10,
                clock=lambda: now[0],
            )
            first = manager.get(client=client, access_token="token", project_id="project")
            self.assertIn("google-antigravity/gemini-3.9-flash", first.model_ids())
            now[0] += 20
            client.fail = True
            second = manager.get(client=client, access_token="token", project_id="project")
            self.assertEqual(second.model_ids(), first.model_ids())

    def test_empty_refresh_does_not_replace_last_known_good(self):
        class Client:
            payload = CATALOG_PAYLOAD

            def fetch_available_models(self, *, access_token, project_id):
                return self.payload

        with tempfile.TemporaryDirectory() as directory:
            client = Client()
            manager = CatalogManager(path=Path(directory) / "catalog.json", ttl_seconds=0)
            first = manager.get(client=client, access_token="token", project_id="project")
            client.payload = {"models": {}}
            second = manager.get(client=client, access_token="token", project_id="project", force=True)
            self.assertEqual(second.model_ids(), first.model_ids())


if __name__ == "__main__":
    unittest.main()
