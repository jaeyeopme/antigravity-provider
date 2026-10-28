# Antigravity Provider

[![tests](https://github.com/jaeyeopme/antigravity-provider/actions/workflows/test.yml/badge.svg)](https://github.com/jaeyeopme/antigravity-provider/actions/workflows/test.yml)

Use the Gemini, Claude, and gpt-oss models of your Google Antigravity account in
[Hermes Agent](https://github.com/NousResearch/hermes-agent). No API key and no
local proxy: the plugin signs in with your Google account and talks to
Antigravity directly from inside Hermes.

> [!CAUTION]
> This is an unofficial integration, not endorsed by Google. It reaches
> Antigravity from outside Google's documented clients, so the Google account
> you use may be restricted, suspended, or lose access. Consider a separate
> account. Sign-in goes through the Antigravity IDE's own OAuth client; if
> Google retires that client, sign-in stops working until the plugin changes.

## Requirements

- Hermes Agent 0.21.5 or newer (`ProviderProfile.create_client` support). CI
  checks 0.21.6 and the latest release.
- Python 3.11 or newer. The plugin uses only the standard library.
- A Google account with Antigravity access.

## Install and sign in

```bash
hermes plugins install jaeyeopme/antigravity-provider --enable
hermes agy login
hermes agy select
```

`hermes agy login` signs in one of two ways:

- **macOS with the `agy` CLI signed in:** reuses the `agy` credential from the
  Keychain. Nothing is copied to disk, and the Keychain item is never changed.
- **Everywhere else:** opens a browser for Google sign-in and saves the result
  in the active Hermes profile.

To use a browser sign-in even when `agy` is available, run
`hermes agy login --no-keychain`. On macOS, running plain `hermes agy login`
again switches back to `agy` and removes the saved browser sign-in.

Every merge to `main` is a release, and `hermes plugins update` takes it. To
stay on one version, pass the commit a
[`vYYYY.M.D` tag](https://github.com/jaeyeopme/antigravity-provider/tags)
points to: `hermes plugins install jaeyeopme/antigravity-provider --ref <commit>`.

`hermes agy select` makes Antigravity the default Hermes provider with your
account's default model. Pass a model ID your account lists to choose another
one, for example `hermes agy select gemini-3-flash`. Restart running Hermes
sessions afterwards.

**Signing in on a remote machine:** the browser redirect goes to
`127.0.0.1:51121` on the machine running Hermes. Forward that port, then open
the printed URL locally:

```bash
ssh -L 51121:127.0.0.1:51121 <host>
hermes agy login --no-browser
```

## Use

| Task | Command |
| --- | --- |
| Pick a model from your account's catalog | `hermes model` |
| Switch model in a session | `/model google-antigravity/<model-id>` (`--global` to keep it) |
| Change reasoning effort | `/reasoning off`, `minimal`, `low`, `medium`, or `high` |
| Check sign-in, token expiry, project, account | `hermes agy status` |

Model IDs can be written with or without the `google-antigravity/` prefix. A
model the backend serves can be used even before it appears in the catalog.

Without a reasoning level, requests use `low`. `xhigh` and `max` act as `high`.
`off` sends a thinking budget of 0 to models that think.

## Troubleshooting

| Symptom | Fix |
| --- | --- |
| `Missing Antigravity credentials` | Run `hermes agy login`. If the `agy` credential no longer works, it falls back to browser sign-in. |
| `Antigravity sign-in expired or was revoked` | Run `hermes agy login`. With the `agy` credential, sign in to `agy` again first. |
| A newly launched model is missing from the picker | The catalog refreshes every four hours. Until then, use it directly with `/model <model-id>` or `hermes agy select <model-id>`. |
| Sign-in fails because port 51121 is busy | `ANTIGRAVITY_OAUTH_PORT=51122 hermes agy login --no-keychain` |
| Requests start failing after an Antigravity update | Set `ANTIGRAVITY_CLIENT_VERSION` to the current `agy` version. |
| Unsure which account or token is in use | `hermes agy status` |

## Sign out and uninstall

```bash
hermes agy logout
hermes plugins remove antigravity-provider
```

`hermes agy logout` removes the saved browser sign-in of the active Hermes
profile and the small provider registration the plugin wrote there. It does not
touch the `agy` Keychain credential. Removing the plugin alone leaves both in
place, and Hermes then warns about the stale registration at every start.

## How it works

### Credentials

A browser sign-in saved in the active Hermes profile always wins. Without one,
the `agy` Keychain credential is used; it is read once per process and its
refreshed token stays in memory. Expired tokens are refreshed automatically,
and a request rejected with 401 is refreshed and retried once. When a
credential has no Cloud Code project yet, the plugin finds or creates one.

### Model catalog

The plugin asks both Antigravity endpoints which models the account can use
(`v1internal:fetchAvailableModels`), merges the answers, and caches them for
four hours. A failed or empty refresh keeps the last good catalog and is not
retried for five minutes; a small built-in catalog is used only before the
first successful refresh.

Backend model IDs are folded into one public model each:

- `*-tiered` becomes one model; reasoning levels pick its thinking budget
  (1k for low, 4k for medium, dynamic for high).
- `*-low`, `*-medium`, `*-high`, `*-thinking`, `*-minimal`, `*-extra-low`, and
  `*-extra-high` variants become one model whose reasoning level picks the
  variant.
- Other IDs stay as they are, and a few legacy agent IDs are kept as aliases.

New models therefore show up without a plugin release. A new wire protocol or
irregular naming still needs code.

### Requests

The plugin converts Hermes' OpenAI-style requests in-process:

- Streaming chat with system, developer, user, assistant, and tool messages.
- `tools` and `tool_choice`, keeping Gemini thought signatures and tool call IDs
  across turns.
- `max_tokens`, `max_completion_tokens`, `temperature`, and `top_p`.
- Images given as data URLs. Remote image URLs become a text placeholder.
- Tool schemas with local `$ref`s, nullable types, and `anyOf`/`oneOf` unions,
  widened to what the backend accepts.

Provider failures, including empty replies, surface as Hermes provider errors,
so Hermes' retry and fallback apply.

### Files

All files live in the active Hermes home (`$HERMES_HOME`, per profile):

| Path | Contents |
| --- | --- |
| `.antigravity_oauth.json` | Browser sign-in tokens, readable only by you. |
| `.antigravity_models.json` | Cached model catalog. |
| `plugins/model-providers/antigravity/` | Small shim that registers the provider; written by `login` and `select`, removed by `logout`. |

### Environment variables

| Variable | Default | Purpose |
| --- | --- | --- |
| `ANTIGRAVITY_OAUTH_PORT` | `51121` | Local port for the sign-in redirect. |
| `ANTIGRAVITY_OAUTH_BIND_HOST` | `127.0.0.1` | Address the sign-in listener binds to. |
| `ANTIGRAVITY_OAUTH_REDIRECT_HOST` | `127.0.0.1` | Host used in the redirect URL. |
| `ANTIGRAVITY_CLIENT_VERSION` | built in | Antigravity client version the plugin presents. |
| `ANTIGRAVITY_HERMES_API_KEY` | `hermes-plugin` | Placeholder Hermes requires; set automatically, not a real key. |

## Development

```bash
python -m venv .venv
. .venv/bin/activate
python -m pip install -e . ruff coverage
ruff check . && ruff format --check .
python -m coverage run -m unittest discover -v && python -m coverage report -m
scripts/validate_hermes.sh
```

`scripts/validate_hermes.sh` installs the checkout as a Hermes directory
plugin when `hermes` and `git` are available. `python scripts/run_in_hermes.py
scripts/e2e_hermes.py` runs a real Hermes agent turn, including a tool call,
against a local fake backend, with the installed `hermes`' own Python.

CI runs all of this for every pull request, the Hermes checks against a fresh
install of the oldest supported and the latest Hermes release on Linux and
Windows, so they need not touch your own Hermes. Run them locally after a
Hermes upgrade to check your setup.

How a change reaches `main`, how versions and the changelog are kept, and what
each module does: [CONTRIBUTING.md](CONTRIBUTING.md). Security reports:
[SECURITY.md](SECURITY.md).
