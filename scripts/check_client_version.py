"""Check, from CI, that the client version the plugin falls back to is still fit to present.

Every Hermes process reads the current Antigravity version from its update server, so users never
need a plugin release to keep up. This job watches the two things that design leaves unwatched:

- The update server. Its address is not a published API; if it moves, every process quietly falls
  back to DEFAULT_CLIENT_VERSION and nobody would notice.
- DEFAULT_CLIENT_VERSION itself. It is only presented when the update server cannot be read, but it
  must not have grown so old that the backend hides models from it.

Exits non-zero, so the scheduled run fails and GitHub mails the maintainer, in either case. Run it
by hand with:

    PYTHONPATH=src python scripts/check_client_version.py
"""

from __future__ import annotations

import datetime
import sys

from antigravity_provider import cloudcode
from antigravity_provider.errors import AntigravityError


def problem(latest: str, today: datetime.date) -> str | None:
    """What is wrong with the built-in version, given the one the update server ships; None if fine."""
    built_in = cloudcode.DEFAULT_CLIENT_VERSION
    if cloudcode._release(latest) <= cloudcode._release(built_in):
        return None
    age = (today - datetime.date.fromisoformat(cloudcode.DEFAULT_CLIENT_VERSION_SET)).days
    if age <= cloudcode.CLIENT_VERSION_MAX_AGE_DAYS:
        return None
    return (
        f"DEFAULT_CLIENT_VERSION {built_in} was set {age} days ago and {latest} is out. "
        f'Set DEFAULT_CLIENT_VERSION = "{latest}" and DEFAULT_CLIENT_VERSION_SET = '
        f'"{today.isoformat()}" in src/antigravity_provider/cloudcode.py with the next release.'
    )


def main() -> int:
    try:
        latest = cloudcode.fetch_released_version()
    except AntigravityError as exc:
        print(f"The update server cannot be read; users fall back to the built-in version: {exc}")
        return 1
    found = problem(latest, datetime.date.today())
    if found:
        print(found)
        return 1
    print(f"Update server ships {latest}; built-in {cloudcode.DEFAULT_CLIENT_VERSION} is fine.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
