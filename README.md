# Antigravity Provider

[![tests](https://github.com/jaeyeopme/antigravity-provider/actions/workflows/test.yml/badge.svg)](https://github.com/jaeyeopme/antigravity-provider/actions/workflows/test.yml)

Google Antigravity provider for Hermes Agent. The plugin registers the
`antigravity` provider, adds the `hermes agy` command group, and translates
Hermes chat requests to Antigravity Cloud Code Assist in-process.

<details open>
<summary><b>⚠️ Account risk notice</b></summary>

> [!CAUTION]
> This is an unofficial integration and is not endorsed by Google. It uses
> Antigravity access from outside Google's documented client surface, so the
> Google account you use may be restricted, suspended, or lose access. Use a
> disposable/separate account if you choose to proceed.

</details>

## Quick start

```bash
hermes plugins install jaeyeopme/antigravity-provider --enable
hermes agy login
hermes agy select
```

The plugin first uses a browser OAuth login saved in the active Hermes profile
at `$HERMES_HOME/.antigravity_oauth.json`. Without that profile override it
imports the existing macOS `agy` Keychain credential. Keychain tokens and the
resolved Cloud Code project are cached for the current process.

```bash
hermes agy login --no-keychain
```

Use `--no-keychain` to create or replace the browser OAuth override. A later
plain `hermes agy login` selects Keychain again and removes that override.
`hermes agy select` uses the account catalog's `defaultAgentModelId`; passing a
model ID always wins.

## Logout and uninstall

`hermes agy logout` removes the saved browser OAuth login for the active Hermes
profile. It does not delete the macOS `agy` Keychain credential.

To remove the plugin and its saved browser OAuth login:

```bash
hermes agy logout
hermes plugins remove antigravity-provider
```

Removing the plugin alone does not remove profile auth state.

## Requirements

- Hermes Agent with `ProviderProfile.create_client` support; verified on 0.21.5.
- Python 3.11+.
- Google account with Antigravity access.

The package uses only the Python standard library.

## Models and reasoning

The plugin fetches the account-scoped catalog from both
`v1internal:fetchAvailableModels` endpoints. Results are normalized into Hermes
model IDs and cached for four hours at
`$HERMES_HOME/.antigravity_models.json`. Failed or empty refreshes retain the
last-known-good catalog; a small static catalog is used only before the first
successful refresh.

Catalog normalization is generic:

- `*-tiered` becomes one public model and keeps the live wire ID and model enum.
- `*-low`, `*-medium`, `*-high`, `*-thinking`, and `*-extra-low` variants become
  one public model with reasoning levels.
- Backend-selected unsuffixed models remain selectable.
- A few legacy agent IDs remain explicit aliases.

This lets catalog-only model launches appear without a plugin release. A new
wire protocol or irregular backend naming still requires code.

Hermes `/reasoning` levels select a discovered route and `thinkingConfig`.
Live per-route budgets win. Tiered Gemini fallback policy is 1k for low, 4k for
medium, and dynamic (`-1`) for high. `off`, `none`, or disabled reasoning sends
`includeThoughts=false` with budget `0` when the model supports thinking.

Bare names such as `gemini-3.8-flash` or `gemini-3.1-pro` are normalized to the
`google-antigravity/` prefix.

## Request support

The native provider client handles:

- Streaming `messages`, including system/developer/user/assistant/tool roles.
- `tools` and `tool_choice`.
- Hermes-style `reasoning_effort`, `reasoning.effort`, and
  `extra_body.reasoning.effort` input hints.
- `max_tokens`, `max_completion_tokens`, `temperature`, and `top_p`.
- Data-URL images as inline data. Remote image URLs become text placeholders.
- Local JSON Schema `$ref` resolution and nullable unions. Other `anyOf`/`oneOf`
  unions fail explicitly instead of being flattened incorrectly.

Provider failures propagate through Hermes retry, fallback, and error telemetry.

## Troubleshooting

| Symptom | Fix |
| --- | --- |
| `Missing Antigravity credentials`. | Run `hermes agy login`; use `--no-keychain` to create a browser OAuth override when the `agy` Keychain credential is stale. |
| A newly launched model is missing. | Re-run the model picker after the four-hour catalog TTL, or run `hermes agy select <model-id>` when the backend already advertises it. |
| OAuth callback port is busy. | Run `ANTIGRAVITY_OAUTH_PORT=51122 hermes agy login --no-keychain`. |

## Development

```bash
python -m venv .venv
. .venv/bin/activate
python -m pip install -e .
python -m unittest discover -v
scripts/validate_hermes.sh
```

`scripts/validate_hermes.sh` also checks directory-plugin installation when
`hermes` and `git` are available.