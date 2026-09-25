# Changelog

## 0.2.0

- Discover and route account models from `fetchAvailableModels`, with a project-scoped last-known-good cache.
- Use Hermes `ProviderProfile.create_client` for native streaming and standard provider error handling.
- Make browser OAuth an explicit profile override and cache Keychain token/project refreshes per process.
- Preserve local JSON Schema references, reject lossy unions, and generate unique duplicate tool-call IDs.
- Fall back across Antigravity endpoints on retryable pre-stream failures and reject empty streams.

## 0.1.0

- Initial Antigravity provider plugin.
