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

The plugin reads an existing macOS `agy` Keychain credential when present.
Otherwise it runs browser OAuth and saves the login in the active Hermes profile
at `$HERMES_HOME/.antigravity_oauth.json`. Each Hermes profile has its own
`$HERMES_HOME`, so browser OAuth logins are profile-scoped.

```bash
hermes agy login --no-keychain
```

Use `--no-keychain` to force browser login. No manual token setup is required.
`hermes agy select` defaults to `google-antigravity/gemini-3.1-pro`.

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

- Hermes Agent with plugin support.
- Python 3.11+.
- Google account with Antigravity access.

The package uses only the Python standard library.

## Models and reasoning

Hermes has generic `/reasoning` levels. Antigravity does not expose that same
interface. The plugin treats Hermes reasoning as an input hint and translates it
into the Antigravity model route plus `thinkingConfig` budget. You can ignore
this unless you tune `/reasoning`.

| Model id | Hermes input | Sent to Antigravity |
| --- | --- | --- |
| `google-antigravity/gemini-3.1-pro` | `minimal`, `low`, `medium` | low route, ~1k thinking budget |
| `google-antigravity/gemini-3.1-pro` | `high`, `xhigh` | agent route, ~10k thinking budget |
| `google-antigravity/gemini-3.5-flash` | `minimal`, `low` | extra-low route, 1k thinking budget |
| `google-antigravity/gemini-3.5-flash` | `medium` | low route, 4k thinking budget |
| `google-antigravity/gemini-3.5-flash` | `high`, `xhigh` | agent route, 10k thinking budget |
| `google-antigravity/claude-sonnet-4-6` | `minimal`, `low`, `medium`, `high` | same route, 1k/4k/8k/16k budget |
| `google-antigravity/claude-opus-4-6` | `minimal`, `low`, `medium`, `high` | thinking route, 1k/4k/8k/16k budget |
| `google-antigravity/gpt-oss-120b` | any enabled level | MaaS route, 8k thinking budget |

`off`, `none`, or disabled reasoning sends `includeThoughts=false` and budget
`0`.

Bare names such as `gemini-3.1-pro` are normalized to the
`google-antigravity/` prefix.

## Request support

The middleware handles:

- `messages`, including system/developer/user/assistant/tool roles.
- `tools` and `tool_choice`.
- Hermes-style `reasoning_effort`, `reasoning.effort`, and
  `extra_body.reasoning.effort` input hints.
- `max_tokens`, `max_completion_tokens`, `temperature`, and `top_p`.
- Data-URL images as inline data. Remote image URLs become text placeholders.

For non-Antigravity providers the middleware passes the request through.

## Troubleshooting

| Symptom | Fix |
| --- | --- |
| `Missing Antigravity credentials`. | Run `hermes agy login`; use `--no-keychain` if the `agy` Keychain credential is stale. |
| `API call failed after 3 retries: Connection error` with endpoint `127.0.0.1:8765`. | Restart Hermes/Desktop so the plugin reloads, then verify `antigravity-provider` is enabled. |
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