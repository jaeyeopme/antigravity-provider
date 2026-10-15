# Changelog

## 0.3.3 - 2026-10-15

- Pick the model for Hermes side tasks (titles, compression, ...) from the account's catalog: the backend's cheap pick (`gemini-3.5-flash-lite`) when listed, else the account default. The fixed `gemini-3.1-pro` returned 404 on accounts without it.
- Show a retired model's notice ("Gemini 3.5 Flash is no longer available...") as the reply. It arrives without a finish reason, so Hermes kept requesting continuations and never showed it.
- Drop retired Gemini 3.5 Flash routes from the offline model list.

## 0.3.2 - 2026-10-15

- Keep tool schemas inside what the backend accepts: drop unsupported fields (`const` becomes a one-value `enum`), send enum values as strings, give arrays `items`, and list only defined properties as `required`. One MCP tool using these failed every request.
- Keep Claude's output limit above its thinking budget; a small `max_tokens` made Claude routes fail with 400.
- Send images from tool results (screenshots) to the model instead of a text placeholder.

## 0.3.1 - 2026-10-15

- Send tool call IDs back with replayed tool calls and results; Claude and gpt-oss routes rejected the next turn after any tool call without them.
- Keep tool parameters named like schema keywords (`definitions`, `additionalProperties`, `$ref`, `anyOf`, ...) instead of dropping them or failing the request.
- Report a streamed reply with no output as a retryable provider error, as non-streamed replies already were.
- Report a non-streamed reply that ends without a finish reason as a retryable provider error instead of returning the cut-off reply as complete.
- Keep token usage when it arrives in its own event after the finish reason.

## 0.3.0 - 2026-10-15

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

## 0.2.2 - 2026-09-26

- Support Hermes asynchronous auxiliary requests through the native Antigravity transport.
- Prefer an unsuffixed live model when the requested reasoning variant is unavailable.
- Keep a live model catalog usable when its optional disk cache cannot be written.

## 0.2.1 - 2026-09-25

- Preserve Hermes tool-schema unions as backend-compatible supersets instead of rejecting or selecting one branch.

## 0.2.0 - 2026-09-25

- Discover and route account models from `fetchAvailableModels`, with a project-scoped last-known-good cache.
- Use Hermes `ProviderProfile.create_client` for native streaming and standard provider error handling.
- Make browser OAuth an explicit profile override and cache Keychain token/project refreshes per process.
- Preserve local JSON Schema references, reject lossy unions, and generate unique duplicate tool-call IDs.
- Fall back across Antigravity endpoints on retryable pre-stream failures and reject empty streams.

## 0.1.0 - 2026-06-28

- Initial Antigravity provider plugin.
