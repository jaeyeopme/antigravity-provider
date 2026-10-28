<!-- What a user notices after this merges, and why. Every merge to main reaches users on their next update. -->

## Kind of change

- [ ] **Code** (`src/`, root `__init__.py`): behavior changes. Version set to the merge date in `src/antigravity_provider/__init__.py` and `plugin.yaml`, and a `## YYYY.M.D` section added to `CHANGELOG.md`.
- [ ] **Everything else** (docs, tests, scripts, CI, metadata): no version bump, no changelog entry.

## Checklist

- [ ] A test covers the change.
- [ ] `ruff check .` and `ruff format .` are clean.
- [ ] The changelog line says what went wrong before and what happens now, in a user's words.
- [ ] Considered the other setups: `agy` Keychain and browser sign-in, macOS/Linux/Windows, Hermes profiles, several Hermes processes on one home, the Hermes versions CI runs.
- [ ] Nothing new logs, prints, or writes a token or the contents of `.antigravity_oauth.json`.
