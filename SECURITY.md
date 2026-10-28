# Security

## Reporting

Use GitHub's private vulnerability reporting: **Security → Report a vulnerability** on this
repository. Do not open a public issue for anything that could expose a sign-in token.

Never put a token, the contents of `.antigravity_oauth.json`, or the `agy` Keychain secret in a
report. A `hermes agy status` output with the account blanked is enough.

You will hear back within a week. A fix ships as a code release on `main` with a changelog line
that credits you, unless you ask otherwise.

## Supported versions

Only the latest commit on `main`. Hermes installs and updates from it, so there is nothing else
to support.

## In scope

- A sign-in token reaching a place it should not: a file other accounts can read, a log,
  terminal output, or any host other than Google's and Antigravity's.
- The local OAuth callback accepting a request that is not from the sign-in just started, or the
  listener being reachable from outside the machine by default.
- A model or tool reply steering the plugin into doing something the user did not ask for.
- The `agy` Keychain item being changed, or its secret copied to disk.

## Out of scope

- Google restricting or suspending an account for using Antigravity from outside its own clients.
  The README warns about it; it is the price of the project.
- The embedded Antigravity IDE OAuth client ID and secret. A desktop application cannot keep its
  client secret confidential (RFC 8252); it is the IDE's public client, not this project's.
- Hermes Agent itself. Report to
  [hermes-agent](https://github.com/NousResearch/hermes-agent/security).
