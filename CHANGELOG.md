# Changelog

Each version is the date its code reached `main` (`YYYY.M.D`), with `.1`, `.2`, ... for later merges the same day.

## 2026.10.28

- Accept tools whose parameter schema has a recursive, remote, or missing `$ref`, or an empty union. One such MCP tool failed every request while it was loaded.
- Merge `allOf` in tool schemas. A property wrapped in it (pydantic v1 does this) lost every field it referenced.
- Read the `agy` Keychain again after a failed read. A Keychain that was locked when Hermes started left it reporting missing credentials until a restart.
- Use a new `agy` sign-in when the old refresh token stops working, instead of failing until Hermes restarts.
- A revoked or expired sign-in says to run `hermes agy login`; before, every request showed a raw `400 invalid_grant`.
- `hermes agy login` failures print one line instead of a traceback; a busy sign-in port names `ANTIGRAVITY_OAUTH_PORT`; an `agy` credential that no longer works falls back to browser sign-in.
- Ask both endpoints for the model list at the same time, so a slow network delays a catalog refresh by one timeout, not two.
- Make the saved sign-in private on Windows. `chmod` does nothing there, so other accounts on the machine could read the tokens, for example with `HERMES_HOME` outside the user profile.
- Keep using a refreshed token when saving it fails (Windows, while another Hermes process reads the file).
- Keep the backend's message for a stream error with a text code such as `RESOURCE_EXHAUSTED`.

## 2026.10.16

- `hermes agy select` refuses a model your account does not list and shows the ones it does. Before, it saved the name anyway and every request failed with 404; without a model and with model discovery failing, it saved `gemini-3.1-pro`.

## 2026.10.15.3

- Pick the model for Hermes side tasks (titles, compression, ...) from the account's catalog: the backend's cheap pick (`gemini-3.5-flash-lite`) when listed, else the account default. The fixed `gemini-3.1-pro` returned 404 on accounts without it.
- Show a retired model's notice ("Gemini 3.5 Flash is no longer available...") as the reply. It arrives without a finish reason, so Hermes kept requesting continuations and never showed it.
- Drop retired Gemini 3.5 Flash routes from the offline model list.

## 2026.10.15.2

- Keep tool schemas inside what the backend accepts: drop unsupported fields (`const` becomes a one-value `enum`), send enum values as strings, give arrays `items`, and list only defined properties as `required`. One MCP tool using these failed every request.
- Keep Claude's output limit above its thinking budget; a small `max_tokens` made Claude routes fail with 400.
- Send images from tool results (screenshots) to the model instead of a text placeholder.

## 2026.10.15.1

- Send tool call IDs back with replayed tool calls and results; Claude and gpt-oss routes rejected the next turn after any tool call without them.
- Keep tool parameters named like schema keywords (`definitions`, `additionalProperties`, `$ref`, `anyOf`, ...) instead of dropping them or failing the request.
- Report a streamed reply with no output as a retryable provider error, as non-streamed replies already were.
- Report a non-streamed reply that ends without a finish reason as a retryable provider error instead of returning the cut-off reply as complete.
- Keep token usage when it arrives in its own event after the finish reason.

## 2026.10.15

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

## 2026.9.26

- Support Hermes asynchronous auxiliary requests through the native Antigravity transport.
- Prefer an unsuffixed live model when the requested reasoning variant is unavailable.
- Keep a live model catalog usable when its optional disk cache cannot be written.

## 2026.9.25.1

- Preserve Hermes tool-schema unions as backend-compatible supersets instead of rejecting or selecting one branch.

## 2026.9.25

- Discover and route account models from `fetchAvailableModels`, with a project-scoped last-known-good cache.
- Use Hermes `ProviderProfile.create_client` for native streaming and standard provider error handling.
- Make browser OAuth an explicit profile override and cache Keychain token/project refreshes per process.
- Preserve local JSON Schema references, reject lossy unions, and generate unique duplicate tool-call IDs.
- Fall back across Antigravity endpoints on retryable pre-stream failures and reject empty streams.

## 2026.6.28

- Initial Antigravity provider plugin.
