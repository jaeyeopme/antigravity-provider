import os
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from antigravity_provider.catalog import CatalogManager, build_catalog, fallback_catalog


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


class Fetch:
    def __init__(self, payload=None, error=None):
        self.payload = payload
        self.error = error
        self.calls = 0

    def __call__(self):
        self.calls += 1
        if self.error is not None:
            raise self.error
        return self.payload


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

    def test_aux_model_is_the_backends_cheap_pick_when_listed(self):
        payload = {
            "models": {"gemini-3.5-flash-lite": {}, "claude-sonnet-4-6": {}},
            "defaultAgentModelId": "claude-sonnet-4-6",
            "commitMessageModelIds": ["gemini-3.5-flash-lite"],
        }
        self.assertEqual(build_catalog(payload).aux_model, "google-antigravity/gemini-3.5-flash-lite")
        tiered = {**payload, "commitMessageModelIds": [], "tieredModelIds": {"flashLite": ["gemini-3.5-flash-lite"]}}
        self.assertEqual(build_catalog(tiered).aux_model, "google-antigravity/gemini-3.5-flash-lite")

    def test_aux_model_falls_back_to_default_when_pick_is_not_listed(self):
        payload = {
            "models": {"claude-sonnet-4-6": {}},
            "defaultAgentModelId": "claude-sonnet-4-6",
            "commitMessageModelIds": ["gemini-3.5-flash-lite"],
        }
        self.assertEqual(build_catalog(payload).aux_model, "google-antigravity/claude-sonnet-4-6")

    def test_unsuffixed_default_beats_nonmatching_thinking_variant(self):
        catalog = build_catalog({
            "models": {
                "gemini-2.5-flash": {
                    "supportsThinking": True,
                    "thinkingBudget": -1,
                },
                "gemini-2.5-flash-thinking": {
                    "supportsThinking": True,
                    "thinkingBudget": -1,
                },
            },
            "agentModelSorts": {
                "gemini-2.5-flash": 1,
                "gemini-2.5-flash-thinking": 2,
            },
        })
        for effort in ("off", "minimal", "low", "medium"):
            route = catalog.resolve("gemini-2.5-flash", effort)
            self.assertEqual(route.wire_model, "gemini-2.5-flash")
        self.assertEqual(
            catalog.resolve("gemini-2.5-flash", "high").wire_model,
            "gemini-2.5-flash-thinking",
        )

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
        with tempfile.TemporaryDirectory() as directory:
            now = [1000.0]
            fetch = Fetch(CATALOG_PAYLOAD)
            manager = CatalogManager(path=Path(directory) / "catalog.json", ttl_seconds=10, clock=lambda: now[0])
            first = manager.get(project_id="project", fetch=fetch)
            self.assertIn("google-antigravity/gemini-3.9-flash", first.model_ids())
            now[0] += 20
            fetch.error = RuntimeError("offline")
            second = manager.get(project_id="project", fetch=fetch)
            self.assertEqual(second.model_ids(), first.model_ids())

    def test_empty_refresh_does_not_replace_last_known_good(self):
        with tempfile.TemporaryDirectory() as directory:
            fetch = Fetch(CATALOG_PAYLOAD)
            manager = CatalogManager(path=Path(directory) / "catalog.json", ttl_seconds=0)
            first = manager.get(project_id="project", fetch=fetch)
            fetch.payload = {"models": {}}
            second = manager.get(project_id="project", fetch=fetch, force=True)
            self.assertEqual(second.model_ids(), first.model_ids())

    def test_cache_write_failure_does_not_discard_live_catalog(self):
        class ReadOnlyCatalogManager(CatalogManager):
            def _save(self, project_key, checked_at, payload):
                raise OSError("read-only cache")

        with tempfile.TemporaryDirectory() as directory:
            manager = ReadOnlyCatalogManager(path=Path(directory) / "catalog.json")
            catalog = manager.get(project_id="project", fetch=Fetch(CATALOG_PAYLOAD))
        self.assertIn("google-antigravity/gemini-3.9-flash", catalog.model_ids())

    def test_disk_cache_is_reused_by_a_new_process(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "catalog.json"
            CatalogManager(path=path).get(project_id="project", fetch=Fetch(CATALOG_PAYLOAD))
            fetch = Fetch(CATALOG_PAYLOAD)
            catalog = CatalogManager(path=path).get(project_id="project", fetch=fetch)
            self.assertEqual(fetch.calls, 0)
            self.assertIn("google-antigravity/gemini-3.9-flash", catalog.model_ids())
            other = Fetch(CATALOG_PAYLOAD)
            CatalogManager(path=path).get(project_id="other-project", fetch=other)
            self.assertEqual(other.calls, 1)

    def test_failed_discovery_backs_off_instead_of_retrying_every_request(self):
        with tempfile.TemporaryDirectory() as directory:
            now = [1000.0]
            fetch = Fetch(error=RuntimeError("down"))
            manager = CatalogManager(path=Path(directory) / "catalog.json", retry_seconds=300, clock=lambda: now[0])
            for _ in range(5):
                catalog = manager.get(project_id="project", fetch=fetch)
            self.assertEqual(fetch.calls, 1)
            self.assertEqual(catalog.model_ids(), fallback_catalog().model_ids())
            now[0] += 301
            fetch.error, fetch.payload = None, CATALOG_PAYLOAD
            catalog = manager.get(project_id="project", fetch=fetch)
            self.assertEqual(fetch.calls, 2)
            self.assertIn("google-antigravity/gemini-3.9-flash", catalog.model_ids())

    def test_stale_catalog_is_served_while_another_thread_refreshes(self):
        with tempfile.TemporaryDirectory() as directory:
            now = [1000.0]
            manager = CatalogManager(path=Path(directory) / "catalog.json", ttl_seconds=10, clock=lambda: now[0])
            stale = manager.get(project_id="project", fetch=Fetch(CATALOG_PAYLOAD))
            now[0] += 20
            started, release = threading.Event(), threading.Event()

            def slow_fetch():
                started.set()
                release.wait(5)
                return CATALOG_PAYLOAD

            worker = threading.Thread(target=manager.get, kwargs={"project_id": "project", "fetch": slow_fetch})
            worker.start()
            started.wait(5)
            began = time.monotonic()
            fetch = Fetch(CATALOG_PAYLOAD)
            served = manager.get(project_id="project", fetch=fetch)
            self.assertLess(time.monotonic() - began, 1)
            self.assertEqual(fetch.calls, 0)
            self.assertEqual(served.model_ids(), stale.model_ids())
            release.set()
            worker.join(5)

    def test_cache_path_follows_hermes_home_at_call_time(self):
        with tempfile.TemporaryDirectory() as first, tempfile.TemporaryDirectory() as second:
            with patch.dict(os.environ, {"HERMES_HOME": first}):
                manager = CatalogManager()
                manager.get(project_id="project", fetch=Fetch(CATALOG_PAYLOAD))
            with patch.dict(os.environ, {"HERMES_HOME": second}):
                manager.get(project_id="other", fetch=Fetch(CATALOG_PAYLOAD))
            self.assertTrue((Path(first) / ".antigravity_models.json").exists())
            self.assertTrue((Path(second) / ".antigravity_models.json").exists())

if __name__ == "__main__":
    unittest.main()
