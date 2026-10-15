#!/usr/bin/env bash
set -euo pipefail

PYTHONPATH="${PWD}/src${PYTHONPATH:+:$PYTHONPATH}" python -m unittest discover -v

# Real Hermes directory-plugin install check. This catches the root plugin.yaml
# + __init__.py shim path used by `hermes plugins install <repo> --enable`.
if command -v hermes >/dev/null 2>&1 && command -v git >/dev/null 2>&1; then
  tmp="$(mktemp -d)"
  trap 'rm -rf "$tmp"' EXIT
  repo="$tmp/repo"
  home="$tmp/home"
  export SRC_ROOT="$(pwd)"
  export TEST_REPO="$repo"
  # A HERMES_HOME outside ~/.hermes makes Hermes build its runtime under it and
  # repoint the user's shared launchers there; pin the user's own runtime instead.
  export HERMES_RUNTIME_DIR="${HERMES_RUNTIME_DIR:-$HOME/.hermes/tools}"
  python - <<'PY'
import os
import shutil
from pathlib import Path

src = Path(os.environ['SRC_ROOT'])
dst = Path(os.environ['TEST_REPO'])
ignore = shutil.ignore_patterns('.git', '.venv', 'venv', '__pycache__', '*.pyc', '.pytest_cache')
shutil.copytree(src, dst, ignore=ignore)
PY
  git -C "$repo" init -q
  git -C "$repo" add .
  git -C "$repo" -c user.name=Hermes -c user.email=hermes@example.invalid commit -q -m init
  HERMES_HOME="$home" hermes plugins install "file://$repo" --force >/dev/null
  HERMES_HOME="$home" hermes plugins enable antigravity-provider >/dev/null
  HERMES_HOME="$home" hermes agy status >/dev/null
  echo 'directory plugin install and CLI registration ok'
fi
