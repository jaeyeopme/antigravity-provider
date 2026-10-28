"""Run a script with the Python and dependencies of the installed `hermes`, on any OS.

    python scripts/run_in_hermes.py scripts/e2e_hermes.py

Hermes prints the command its launcher runs; this swaps the CLI module it starts for the given
script, so the script sees the same imports `hermes` does.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys

CLI_ENTRY = "runpy.run_module('hermes_cli.main', run_name='__main__', alter_sys=True)"


def main() -> int:
    if len(sys.argv) != 2:
        raise SystemExit(f"usage: {sys.argv[0]} <script.py>")
    hermes = shutil.which("hermes")
    if hermes is None:
        raise SystemExit("hermes is not on PATH")
    command = json.loads(subprocess.check_output([hermes, "--print-runtime-command"], text=True))
    code = command[3] if len(command) > 3 and command[1:3] == ["-I", "-c"] else ""
    if CLI_ENTRY not in code:
        raise SystemExit(f"unexpected hermes runtime command: {command}")
    script = f"sys.argv = [{sys.argv[1]!r}]; runpy.run_path({sys.argv[1]!r}, run_name='__main__')"
    return subprocess.call([command[0], "-I", "-c", code.replace(CLI_ENTRY, script)])


if __name__ == "__main__":
    sys.exit(main())
