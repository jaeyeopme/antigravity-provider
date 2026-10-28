# Contributing

Thanks for helping. This plugin has real users, and every merge to `main` reaches them on their
next `hermes plugins update`, with no release step in between. The rules below exist so that a
change that is right on your machine is also right on theirs.

## Before you start

- Bugs, missing models, and ideas go through the
  [issue templates](https://github.com/jaeyeopme/antigravity-provider/issues/new/choose).
  A problem in Hermes itself (installing it, other providers, the TUI) belongs in
  [hermes-agent](https://github.com/NousResearch/hermes-agent/issues).
- Anything that could expose a sign-in token goes through [SECURITY.md](SECURITY.md), not an issue.
- For more than a small fix, open an issue first so the approach is agreed before the code exists.

## Setup

```bash
python -m venv .venv
. .venv/bin/activate
python -m pip install -e . ruff coverage
ruff check . && ruff format --check .
python -m coverage run -m unittest discover -v && python -m coverage report -m
scripts/validate_hermes.sh
python scripts/run_in_hermes.py scripts/e2e_hermes.py
```

`scripts/validate_hermes.sh` installs the checkout as a Hermes directory plugin when `hermes` and
`git` are available. `scripts/e2e_hermes.py` runs a real Hermes agent turn, including a tool call,
against a local fake backend, with the installed `hermes`' own Python.

The plugin uses only the standard library. Do not add a dependency.

## How a change lands

- Every change, code or not, goes through a pull request and is squash-merged once the `ci`
  check passes. `main` is protected; nothing is pushed to it directly.
- One pull request per batch of work, one commit per change inside it.
- **Code** is anything that changes how the plugin behaves: `src/` and the root `__init__.py`.
  A code pull request sets the version to its merge date in
  `src/antigravity_provider/__init__.py` and `plugin.yaml`: `YYYY.M.D` without leading zeros
  (`2026.10.16`), with `.1`, `.2`, ... for another code merge on the same day. It adds a section
  headed `## YYYY.M.D` to `CHANGELOG.md`. A test keeps the three in step.
- **Everything else** (docs, tests, scripts, CI, descriptive metadata such as the `plugin.yaml`
  description) needs no version bump or changelog entry.
- CI tags each new version on `main` as `vYYYY.M.D[.n]`. There are no GitHub releases: Hermes
  installs from `main`. A user who wants to pin or roll back runs
  `hermes plugins install jaeyeopme/antigravity-provider --ref <commit>` with the commit a tag
  points to.

## What a pull request needs

- A test for the change. The suite runs in about a second; keep it that way, with fakes instead
  of the network.
- `ruff check .` and `ruff format .` clean. CI enforces both.
- A changelog line a user can act on: what went wrong before and what happens now, not what the
  code does. `CHANGELOG.md` shows the tone.
- Thought given to every way the plugin is used: the `agy` Keychain credential and browser
  sign-in; macOS, Linux and Windows; Hermes profiles (`HERMES_HOME`); several Hermes processes
  sharing one home; the Hermes versions CI runs. A fix that is right for your setup and wrong for
  one of these ships to everyone.
- Nothing new that logs, prints, or writes a token or the contents of `.antigravity_oauth.json`.
- Comments only for the why the code cannot show, in one line.

## Modules

In `src/antigravity_provider/`, from Hermes inward:

| Module | Responsibility |
| --- | --- |
| `hermes_plugin.py` | Plugin entry point: `hermes agy` commands and the request middleware. |
| `hermes_provider.py` | Registers the `antigravity` provider profile. Generated shims import it, so keep its path. |
| `hermes_client.py` | OpenAI-client-shaped facade Hermes calls; sync and async, closable streams. |
| `service.py` | One request end to end: credentials, model routing, 401 refresh and retry. |
| `request.py`, `schema.py` | OpenAI request and tool schemas to the Cloud Code body. |
| `response.py` | Cloud Code chunks to OpenAI completions and stream chunks. |
| `client.py` | HTTP and SSE transport with endpoint fallback. |
| `catalog.py` | Model discovery, routing, and the last-known-good cache. |
| `auth.py`, `credentials.py`, `oauth.py`, `cloudcode.py` | Credential choice and refresh, storage and Keychain, Google OAuth, project onboarding. |
| `models.py`, `errors.py`, `net.py`, `fileio.py`, `paths.py` | Model ID and effort normalization, error type, HTTP helpers, private file writes, Hermes home paths. |
