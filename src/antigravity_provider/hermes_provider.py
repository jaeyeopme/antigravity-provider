from __future__ import annotations

from typing import Any

from .antigravity_client import ANTIGRAVITY_ENDPOINTS
from .catalog import catalog_manager, fallback_catalog
from .models import DEFAULT_MODEL, normalize_effort

PROVIDER_NAME = "antigravity"
PLACEHOLDER_API_KEY_ENV = "ANTIGRAVITY_HERMES_API_KEY"
PLACEHOLDER_API_KEY = "hermes-plugin"
PROVIDER_BASE_URL = ANTIGRAVITY_ENDPOINTS[0]


def _reasoning_effort(reasoning_config: dict | None) -> str | None:
    if not isinstance(reasoning_config, dict):
        return None
    if reasoning_config.get("enabled") is False:
        return "off"
    effort = str(reasoning_config.get("effort") or "").strip()
    return normalize_effort(effort) if effort else None


def register_provider_profile() -> bool:
    """Register the Antigravity native client and account-scoped model catalog."""
    try:
        from providers import register_provider
        from providers.base import OMIT_TEMPERATURE, ProviderProfile
    except Exception:
        return False

    class AntigravityProfile(ProviderProfile):
        def create_client(self, **client_kwargs: Any) -> Any:
            from .runtime import HermesAntigravityClient

            return HermesAntigravityClient(**client_kwargs)

        def build_api_kwargs_extras(
            self,
            *,
            reasoning_config: dict | None = None,
            **context: Any,
        ) -> tuple[dict[str, Any], dict[str, Any]]:
            effort = _reasoning_effort(reasoning_config)
            return {}, ({"reasoning_effort": effort} if effort else {})

        def get_max_tokens(self, model: str | None) -> int | None:
            return catalog_manager.current().max_tokens(model or DEFAULT_MODEL)

        def fetch_models(self, **kwargs: Any) -> list[str] | None:
            from .runtime import load_model_catalog

            try:
                return load_model_catalog().model_ids()
            except Exception:
                return None

    fallback_models = tuple(fallback_catalog().model_ids())
    register_provider(
        AntigravityProfile(
            name=PROVIDER_NAME,
            aliases=("google-antigravity",),
            display_name="Google Antigravity",
            description="Google Antigravity via Hermes native provider client",
            env_vars=(PLACEHOLDER_API_KEY_ENV,),
            base_url=PROVIDER_BASE_URL,
            auth_type="api_key",
            supports_health_check=False,
            supports_vision=True,
            fallback_models=fallback_models,
            default_aux_model=DEFAULT_MODEL,
            fixed_temperature=OMIT_TEMPERATURE,
        )
    )
    return True


# Directory-style model-provider plugins are imported for side effects.
register_provider_profile()
