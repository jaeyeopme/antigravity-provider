# hermes-plugin-antigravity-subscription

[![tests](https://github.com/jaeyeopme/hermes-plugin-antigravity-subscription/actions/workflows/test.yml/badge.svg)](https://github.com/jaeyeopme/hermes-plugin-antigravity-subscription/actions/workflows/test.yml)

A [Hermes](https://github.com/NousResearch/hermes-agent) model provider plugin for the Gemini, Claude, and gpt-oss
models of your Google Antigravity account. No API key, no local proxy, and no `agy` process: the plugin signs in
with your Google account and calls the models directly from inside Hermes, so Hermes' own system prompt and tools
go straight to the model with no second agent in between.

Plugins that run Google's `agy` CLI let a Google client make the requests. This one makes them itself, which is
what the caution below is about.

> [!CAUTION]
> This is an unofficial integration, not endorsed by Google. It reaches
> Antigravity from outside Google's documented clients, so the Google account
> you use may be restricted, suspended, or lose access. Consider a separate
> account. Sign-in goes through the Antigravity IDE's own OAuth client; if
> Google retires that client, sign-in stops working until the plugin changes.

## What it does

- Registers the `google-antigravity` provider in Hermes, with the models your account lists.
- **Streaming chat** with tools, images (data URLs), and reasoning levels.
- **New models** show up without a plugin release: the catalog is read from your account.
- **No image generation.** The plugin does not provide an `image_gen` provider for Hermes' `image_generate`. In November 2026 the only image model Antigravity lists (`gemini-3.1-flash-image`) failed with `500 Internal error encountered.`, in the official `agy` client too. Configure another `image_gen` provider. Details: [docs/image-generation.md](docs/image-generation.md).

## Requirements

- Hermes `>=0.21.5`. CI checks 0.21.6 and the latest release.
- Python 3.11 or newer. Standard library only.
- A Google account with Antigravity access.

## Install

```sh
hermes plugins install jaeyeopme/hermes-plugin-antigravity-subscription --enable
hermes agy login
hermes agy select
```

- `hermes agy login`: on macOS with the `agy` CLI signed in, reuses its Keychain credential (read-only).
  Elsewhere, or with `--no-keychain`, it opens a browser for Google sign-in.
- `hermes agy select [model-id]`: makes Antigravity the default provider. Restart running Hermes sessions afterwards.

**Remote machine**: the sign-in redirect goes to `127.0.0.1:51121` on the machine running Hermes.

```sh
ssh -L 51121:127.0.0.1:51121 <host>
hermes agy login --no-browser
```

## Use

| Task | Command |
|---|---|
| Pick a model | `hermes model` |
| Switch model in a session | `/model google-antigravity/<model-id>` (`--global` to keep it) |
| Change reasoning effort | `/reasoning off`, `minimal`, `low`, `medium`, or `high` (default `low`) |
| Check sign-in, token expiry, project, account | `hermes agy status` |

The `google-antigravity/` prefix is optional. A model the backend serves works even before it appears in the catalog.

## Troubleshooting

| Message | Cause and fix |
|---|---|
| `Missing Antigravity credentials` | Run `hermes agy login`. |
| `Antigravity sign-in expired or was revoked` | Run `hermes agy login`. With the `agy` credential, sign in to `agy` again first. |
| A new model is missing from the picker | The catalog refreshes every four hours. Use `/model <model-id>` meanwhile. |
| Port 51121 is busy | `ANTIGRAVITY_OAUTH_PORT=51122 hermes agy login --no-keychain` |
| `This version of Antigravity is no longer supported` | Restart Hermes; the version is read again on its first request. If it still fails, set `ANTIGRAVITY_CLIENT_VERSION` to the current Antigravity version. |
| Something broke after `hermes plugins update` | Every merge to `main` is a release. Go back with `hermes plugins install jaeyeopme/hermes-plugin-antigravity-subscription --force --ref <commit>`, using the commit of an earlier [tag](https://github.com/jaeyeopme/hermes-plugin-antigravity-subscription/tags). |

## Privacy

- Tokens go only to Google's sign-in and Antigravity endpoints, and are never logged.
- A browser sign-in is saved in `$HERMES_HOME/.antigravity_oauth.json`, readable only by you.
  The `agy` Keychain item is never changed or copied to disk.
- Report a security problem privately: **Security → Report a vulnerability** on this repository.

## How it works

- **Credentials**: a browser sign-in in the active Hermes profile wins, then the `agy` Keychain credential.
  Expired tokens are refreshed; a 401 is refreshed and retried once. A missing Cloud Code project is found or created.
- **Client version**: the backend hides newer models from old client versions and in time rejects them, so the
  plugin presents itself as the current Antigravity IDE (`antigravity/hub/<version>`, the form the IDE sends).
  `agy` sends `antigravity/cli/<version>` and gets the same models, but the backend refuses old `cli` versions
  much sooner than old `hub` ones, and `hub` is what oh-my-pi uses for direct calls. The plugin reads the
  IDE's version from Antigravity's update server once per Hermes process, on the first request, and saves it.
  When that server cannot be reached it presents the saved version or the one built into the plugin, whichever
  is newer. A weekly CI job warns the maintainer if that server stops answering or the built-in version grows old.
- **Catalog**: both Antigravity endpoints are asked (`v1internal:fetchAvailableModels`), merged, and cached for
  four hours. Variants such as `*-low`, `*-high`, `*-thinking`, and `*-tiered` fold into one model whose reasoning
  level picks the variant or thinking budget.
- **Requests**: Hermes' OpenAI-style requests are converted in-process: messages, `tools` and `tool_choice`
  (keeping Gemini thought signatures), `max_tokens`, `temperature`, `top_p`, and tool schemas widened to what the
  backend accepts. Failures surface as Hermes provider errors, so Hermes' retry and fallback apply.
- **Files** in `$HERMES_HOME`: `.antigravity_oauth.json` (sign-in), `.antigravity_models.json` (catalog cache),
  `.antigravity_client_version.json` (last client version read), `plugins/model-providers/antigravity/` (a small
  shim that registers the provider; written by `login` and `select`).
- **Environment**: `ANTIGRAVITY_OAUTH_PORT`, `ANTIGRAVITY_OAUTH_BIND_HOST`, `ANTIGRAVITY_OAUTH_REDIRECT_HOST`
  (sign-in listener), `ANTIGRAVITY_CLIENT_VERSION` (client version presented, instead of the one read).

## Uninstall

```sh
hermes agy logout
hermes plugins remove antigravity-subscription
```

Installed before the rename? The plugin is still called `antigravity-provider` there.
`logout` removes the saved sign-in and the provider shim; without it, Hermes warns about the shim at every start.

## Development

```sh
python -m venv .venv && . .venv/bin/activate
python -m pip install -e . ruff coverage
ruff check . && ruff format --check .
python -m coverage run -m unittest discover -v && python -m coverage report -m
scripts/validate_hermes.sh                              # install the checkout into a throwaway Hermes
python scripts/run_in_hermes.py scripts/e2e_hermes.py   # a real agent turn against a fake backend
```

Versioning, the changelog, and the module map: [CONTRIBUTING.md](CONTRIBUTING.md).

## License

[MIT](LICENSE)
