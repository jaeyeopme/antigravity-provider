# Changelog

## 0.3.0

- Preserve real Gemini thought signatures across turns through Hermes' tool-call `extra_content`; the skip placeholder is only used when history has none.
- Give every tool call a unique ID; identical calls in different turns no longer share one.
- Report `MALFORMED_FUNCTION_CALL`/`UNEXPECTED_TOOL_CALL` turns with no output as retryable provider errors instead of empty replies.
- Make streams safe to close from another thread or after an async cancel, closing the upstream HTTP response.
- Back off for five minutes after a failed model discovery instead of retrying on every request, serve the last-known-good catalog while a refresh runs, and refresh an expired token for discovery.
- Ignore OAuth callbacks whose `state` does not match instead of ending the login.
- Resolve credential and catalog files through Hermes' own home resolution (profiles, Windows), at call time; a login saved at the old location keeps working.
- Reuse a token another Hermes process already refreshed instead of refreshing again.
- `hermes agy status` shows token expiry and project; `ANTIGRAVITY_CLIENT_VERSION` overrides the presented client version.
- Internal: split into credential, OAuth, transport, request, response, service, and Hermes layers; one version source.

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
