# Changelog

## 0.2.2

- Support Hermes asynchronous auxiliary requests through the native Antigravity transport.
- Prefer an unsuffixed live model when the requested reasoning variant is unavailable.
- Keep a live model catalog usable when its optional disk cache cannot be written.

## 0.2.1

- Preserve Hermes tool-schema unions as backend-compatible supersets instead of rejecting or selecting one branch.

## 0.2.0

- Discover and route account models from `fetchAvailableModels`, with a project-scoped last-known-good cache.
- Use Hermes `ProviderProfile.create_client` for native streaming and standard provider error handling.
- Make browser OAuth an explicit profile override and cache Keychain token/project refreshes per process.
- Preserve local JSON Schema references, reject lossy unions, and generate unique duplicate tool-call IDs.
- Fall back across Antigravity endpoints on retryable pre-stream failures and reject empty streams.

## 0.1.0

- Initial Antigravity provider plugin.
