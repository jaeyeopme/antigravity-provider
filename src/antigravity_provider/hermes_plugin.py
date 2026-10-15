"""Hermes plugin entry point: `hermes agy` CLI, request middleware, and provider registration."""

from __future__ import annotations

import argparse
import time
from pathlib import Path
from typing import Any

from . import __version__
from .hermes_provider import PLACEHOLDER_API_KEY, PLACEHOLDER_API_KEY_ENV, PROVIDER_BASE_URL, PROVIDER_NAME, register_provider_profile
from .credentials import SOURCE_KEYCHAIN
from .catalog import fallback_catalog
from .models import normalize_model_id, strip_provider_prefix
from .paths import hermes_home
from .service import default_service

PROVIDER_ALIASES = {PROVIDER_NAME, "google-antigravity"}


def antigravity_llm_request(**kwargs: Any) -> dict[str, dict[str, Any]]:
    """Pass the Hermes session id through so Antigravity sees one session per conversation."""
    request = dict(kwargs.get("request") or {})
    if (kwargs.get("provider") or "").strip().lower() in PROVIDER_ALIASES:
        session_id = kwargs.get("session_id")
        if session_id:
            request["_antigravity_session_id"] = str(session_id)
    return {"request": request}


def ensure_provider_profile_files(root: Path | None = None) -> Path:
    """Write the model-provider shim Hermes imports to register the `antigravity` profile.

    The generated module only imports `antigravity_provider.hermes_provider`, so it keeps working
    across plugin updates; that import path is a compatibility contract.
    """
    plugin_dir = Path(root or hermes_home()).expanduser() / "plugins" / "model-providers" / "antigravity"
    plugin_dir.mkdir(parents=True, exist_ok=True)
    (plugin_dir / "__init__.py").write_text(
        "import sys\n"
        "from pathlib import Path\n\n"
        "_src = Path(__file__).resolve().parents[2] / 'antigravity-provider' / 'src'\n"
        "if _src.is_dir() and str(_src) not in sys.path:\n"
        "    sys.path.insert(0, str(_src))\n\n"
        "from antigravity_provider.hermes_provider import register_provider_profile\n"
        "register_provider_profile()\n",
        encoding="utf-8",
    )
    (plugin_dir / "plugin.yaml").write_text(
        "name: antigravity\n"
        "kind: model-provider\n"
        f"version: {__version__}\n"
        "description: Google Antigravity provider profile\n",
        encoding="utf-8",
    )
    return plugin_dir


def _save_placeholder_api_key() -> None:
    # Hermes expects an API key env var for api_key providers; the real auth is OAuth.
    try:
        from hermes_cli.config import get_env_value, save_env_value

        if not (get_env_value(PLACEHOLDER_API_KEY_ENV) or "").strip():
            save_env_value(PLACEHOLDER_API_KEY_ENV, PLACEHOLDER_API_KEY)
    except Exception:
        return


def _setup_cli(parser: argparse.ArgumentParser) -> None:
    sub = parser.add_subparsers(dest="antigravity_command")

    login = sub.add_parser("login", help="use agy Keychain credentials, falling back to browser OAuth")
    login.add_argument("--no-keychain", action="store_true", help="skip agy Keychain and run browser OAuth")
    login.add_argument("--no-browser", action="store_true", help="print the auth URL instead of opening a browser")
    login.add_argument("--timeout", type=int, default=300, help="seconds to wait for the OAuth callback")

    select = sub.add_parser("select", help="set Antigravity as the active Hermes model without opening the model picker")
    select.add_argument("model", nargs="?")

    sub.add_parser("status", help="show credential status")
    sub.add_parser("logout", help="remove saved browser OAuth credentials")


def _select_model(model_id: str | None) -> None:
    try:
        from hermes_cli.config import load_config, save_config
    except Exception as exc:
        raise SystemExit(f"Hermes config helpers are not available: {exc}") from exc
    try:
        catalog = default_service().catalog()
    except Exception:
        catalog = fallback_catalog()
    # The built-in list stands in when discovery fails; it is not this account's list.
    listed = catalog.model_ids() if catalog is not fallback_catalog() else None
    if not model_id:
        if listed is None:
            raise SystemExit("Could not load your Antigravity models. Run `hermes agy login`, or pass a model ID.")
        model_id = catalog.default_model
    elif listed is not None and normalize_model_id(model_id) not in listed:
        names = ", ".join(strip_provider_prefix(model) for model in listed)
        raise SystemExit(f"Your Antigravity account does not list {model_id}. Available: {names}")
    config = load_config()
    model_cfg = config.get("model")
    if not isinstance(model_cfg, dict):
        model_cfg = {"default": model_cfg} if model_cfg else {}
    model_cfg.update(provider=PROVIDER_NAME, default=model_id, base_url=PROVIDER_BASE_URL, api_mode="chat_completions")
    config["model"] = model_cfg
    save_config(config)
    print(f"Default Hermes model set to {model_id} via provider '{PROVIDER_NAME}'.")
    print("Restart any running Hermes/Desktop session to use updated plugin code.")


def _status() -> None:
    status = default_service().credentials.describe()
    print(f"credentials: {status['source']}")
    print(f"access token: {'yes' if status['has_access_token'] else 'no'}")
    print(f"refresh token: {'yes' if status['has_refresh_token'] else 'no'}")
    if status["expires_at"]:
        state = "expired" if status["expires_at"] <= time.time() else "valid"
        print(f"access token expiry: {time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(status['expires_at']))} ({state})")
    if status["project_id"]:
        print(f"project: {status['project_id']}")
    if status["email"]:
        print(f"account: {status['email']}")


def _handle_cli(args: argparse.Namespace) -> None:
    command = getattr(args, "antigravity_command", None) or "status"
    credentials = default_service().credentials
    if command == "login":
        ensure_provider_profile_files()
        _save_placeholder_api_key()
        result = credentials.login(use_keychain=not args.no_keychain, open_browser=not args.no_browser, timeout=args.timeout)
        source = "agy Keychain" if result.source == SOURCE_KEYCHAIN else "browser OAuth"
        print(f"Antigravity login complete ({source}{', ' + result.email if result.email else ''}).")
    elif command == "select":
        ensure_provider_profile_files()
        _save_placeholder_api_key()
        _select_model(args.model)
    elif command == "logout":
        credentials.logout()
        print("Saved Antigravity browser OAuth credentials removed.")
    else:
        _status()


def register(ctx: Any) -> None:
    register_provider_profile()
    ctx.register_cli_command(
        name="agy",
        help="Manage the Google Antigravity Hermes provider plugin",
        description="Login, status, and model selection helpers for Google Antigravity.",
        setup_fn=_setup_cli,
        handler_fn=_handle_cli,
    )
    ctx.register_middleware("llm_request", antigravity_llm_request)
