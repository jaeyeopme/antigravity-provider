from __future__ import annotations

from typing import Any

from .catalog import catalog_manager
from .client import ANTIGRAVITY_ENDPOINTS
from .models import normalize_effort

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
        @property
        def default_aux_model(self) -> str:
            # Hermes reads this for side tasks. A constant rots when a model is retired, so answer
            # from the account's last catalog (no network).
            return catalog_manager.current().aux_model

        @default_aux_model.setter
        def default_aux_model(self, value: str) -> None:
            pass  # assigned by the dataclass __init__; the live catalog decides

        def create_client(self, **client_kwargs: Any) -> Any:
            from .hermes_client import HermesAntigravityClient

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
            # Hot path: answer from the last catalog without network calls.
            return catalog_manager.current().max_tokens(model or "")

        def fetch_models(self, **kwargs: Any) -> list[str] | None:
            from .service import default_service

            try:
                return default_service().catalog().model_ids()
            except Exception:
                return None

    def picker_catalog(force_refresh: bool) -> list[str] | None:
        # Hermes shows this list as it is, and passes True when it refreshes its own hour-old copy
        # or on `/model --refresh`.
        from .service import default_service

        try:
            return default_service().catalog(force=force_refresh).model_ids()
        except Exception:
            return None  # Hermes then asks fetch_models

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
            picker_catalog=picker_catalog,
            fixed_temperature=OMIT_TEMPERATURE,
        )
    )
    return True


# Directory-style model-provider plugins are imported for side effects.
register_provider_profile()
