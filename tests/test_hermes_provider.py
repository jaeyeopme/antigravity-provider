import sys
import types
import unittest
from unittest.mock import patch

from antigravity_provider import hermes_provider
from antigravity_provider.catalog import build_catalog


class ProviderProfile:
    """Hermes' dataclass: its __init__ assigns every field, default_aux_model included."""

    default_aux_model = ""

    def __init__(self, default_aux_model: str = "", **fields):
        self.default_aux_model = default_aux_model
        vars(self).update(fields)


def fake_hermes(registered):
    providers = types.ModuleType("providers")
    providers.register_provider = registered.append
    base = types.ModuleType("providers.base")
    base.OMIT_TEMPERATURE = object()
    base.ProviderProfile = ProviderProfile
    return {"providers": providers, "providers.base": base}


class ProviderProfileTests(unittest.TestCase):
    def test_aux_model_follows_the_live_account_catalog(self):
        registered = []
        with patch.dict(sys.modules, fake_hermes(registered)):
            self.assertTrue(hermes_provider.register_provider_profile())
        catalog = build_catalog(
            {
                "models": {"gemini-3.5-flash-lite": {}, "claude-sonnet-4-6": {}},
                "defaultAgentModelId": "claude-sonnet-4-6",
                "commitMessageModelIds": ["gemini-3.5-flash-lite"],
            }
        )
        with patch.object(hermes_provider.catalog_manager, "current", return_value=catalog):
            self.assertEqual(
                registered[0].default_aux_model, "google-antigravity/gemini-3.5-flash-lite"
            )

    def test_reasoning_config_becomes_the_reasoning_effort_kwarg(self):
        registered = []
        with patch.dict(sys.modules, fake_hermes(registered)):
            hermes_provider.register_provider_profile()
        extras = registered[0].build_api_kwargs_extras
        self.assertEqual(
            extras(reasoning_config={"enabled": False}), ({}, {"reasoning_effort": "off"})
        )
        self.assertEqual(
            extras(reasoning_config={"effort": "xhigh"}), ({}, {"reasoning_effort": "high"})
        )
        self.assertEqual(extras(reasoning_config=None), ({}, {}))

    def test_picker_catalog_fetches_live_when_hermes_forces_a_refresh(self):
        registered = []
        with patch.dict(sys.modules, fake_hermes(registered)):
            hermes_provider.register_provider_profile()
        live = build_catalog({"models": {"gemini-3.5-flash-lite": {}}})
        forced = []

        class Service:
            def catalog(self, *, force=False):
                forced.append(force)
                return live

        with patch("antigravity_provider.service.default_service", return_value=Service()):
            self.assertEqual(registered[0].picker_catalog(True), live.model_ids())
            registered[0].picker_catalog(False)
        self.assertEqual(forced, [True, False])

    def test_picker_catalog_hands_over_to_hermes_when_the_catalog_cannot_be_read(self):
        registered = []
        with patch.dict(sys.modules, fake_hermes(registered)):
            hermes_provider.register_provider_profile()
        with patch("antigravity_provider.service.default_service", side_effect=RuntimeError):
            self.assertIsNone(registered[0].picker_catalog(True))


if __name__ == "__main__":
    unittest.main()
