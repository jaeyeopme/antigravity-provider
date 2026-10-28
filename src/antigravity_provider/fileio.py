from __future__ import annotations

import getpass
import json
import os
import subprocess
import tempfile
from pathlib import Path
from typing import Any


def write_private_json(path: Path, data: Any) -> None:
    """Atomically write JSON readable only by the current user."""
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(path.parent, 0o700)
    except OSError:
        pass
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=str(path.parent), text=True)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            if os.name == "nt":
                _restrict_to_current_user(temporary)  # before any secret is written to it
            json.dump(data, handle, indent=2, sort_keys=True)
            handle.write("\n")
        os.chmod(temporary, 0o600)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def _restrict_to_current_user(path: str) -> None:
    """Windows ignores chmod: drop inherited ACL entries and grant only the current user."""
    domain, user = os.environ.get("USERDOMAIN"), os.environ.get("USERNAME")
    account = f"{domain}\\{user}" if domain and user else getpass.getuser()
    try:
        subprocess.run(
            ["icacls", path, "/inheritance:r", "/grant:r", f"{account}:F"],
            check=True,
            capture_output=True,
            timeout=10,
        )
    except (subprocess.SubprocessError, OSError) as exc:
        # Callers treat OSError as a failed write: login reports it, background refreshes go on.
        raise OSError(f"could not make {path} private: {exc}") from exc


def read_json(path: Path) -> Any:
    """Return parsed JSON, or None when the file is missing or unreadable."""
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
