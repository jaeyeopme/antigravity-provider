#!/usr/bin/env bash
set -euo pipefail

# Real Hermes directory-plugin install check. This catches the root plugin.yaml
# + __init__.py shim path used by `hermes plugins install <repo> --enable`.
# A temp HERMES_HOME makes Hermes build its runtime under it and repoint the
# user's shared launchers there. Pin the runtime the user's launcher already
# runs (<store>/<python entry>/bin/python3, or python.exe on Windows), and check
# the launcher after.
# Hermes builds without --print-runtime-command skip the check instead of
# risking the user's install.
launch=""
if ! command -v hermes >/dev/null 2>&1 || ! command -v git >/dev/null 2>&1; then
  skip='hermes or git is missing'
else
  launch="$(hermes --print-runtime-command 2>/dev/null)" || launch=""
  if [ -z "${HERMES_RUNTIME_DIR:-}" ]; then
    HERMES_RUNTIME_DIR="$(LAUNCH="$launch" python - <<'PY'
import json
import os
from pathlib import Path

try:
    py = Path(json.loads(os.environ['LAUNCH'])[0])
except (ValueError, TypeError, IndexError, KeyError):
    raise SystemExit(0)
store = next((parent for parent in py.parents[1:3] if (parent / 'facts.json').is_file()), None)
if store is not None:
    print(store)
PY
)"
    export HERMES_RUNTIME_DIR
  fi
  skip=''
  [ -n "$HERMES_RUNTIME_DIR" ] || skip='this hermes does not report its runtime; set HERMES_RUNTIME_DIR to run it'
fi
if [ -n "$skip" ]; then
  echo "skipped the Hermes plugin install check: $skip"
else
  tmp="$(mktemp -d)"
  trap 'rm -rf "$tmp"' EXIT
  # Git Bash on Windows: hermes and python take C:/... paths, not /tmp/...
  src="$(pwd)"
  if command -v cygpath >/dev/null 2>&1; then tmp="$(cygpath -m "$tmp")"; src="$(cygpath -m "$src")"; fi
  repo="$tmp/repo"
  home="$tmp/home"
  export SRC_ROOT="$src"
  export TEST_REPO="$repo"
  python - <<'PY'
import os
import shutil
from pathlib import Path

src = Path(os.environ['SRC_ROOT'])
dst = Path(os.environ['TEST_REPO'])
ignore = shutil.ignore_patterns(
    '.git', '.venv', 'venv', '__pycache__', '*.pyc', '.pytest_cache',
    'build', 'dist', '*.egg-info', '.ruff_cache', '.mypy_cache',
)
shutil.copytree(src, dst, ignore=ignore)
PY
  git -C "$repo" init -q
  git -C "$repo" add .
  git -C "$repo" -c user.name=Hermes -c user.email=hermes@example.invalid commit -q -m init
  HERMES_HOME="$home" hermes plugins install "file:///${repo#/}" --force >/dev/null
  HERMES_HOME="$home" hermes plugins enable antigravity-provider >/dev/null
  HERMES_HOME="$home" hermes agy status >/dev/null
  if [ -n "$launch" ] && [ "$(hermes --print-runtime-command)" != "$launch" ]; then
    echo "hermes launcher changed during the check; it was: $launch" >&2
    exit 1
  fi
  echo 'directory plugin install and CLI registration ok'
fi
