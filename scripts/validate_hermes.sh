#!/usr/bin/env bash
set -euo pipefail

python -m unittest discover -v

# Direct import check for the pip/editable path.
HERMES_HOME="${HERMES_HOME:-$(mktemp -d)}" python - <<'PY'
from antigravity_provider.hermes_plugin import register

class Ctx:
    def __init__(self):
        self.cli = {}
        self.middleware = []
    def register_cli_command(self, **kwargs):
        self.cli[kwargs['name']] = kwargs
    def register_middleware(self, kind, callback):
        self.middleware.append((kind, callback))

ctx = Ctx()
register(ctx)
assert 'agy' in ctx.cli
assert any(kind == 'llm_execution' for kind, _ in ctx.middleware)
print('plugin registration ok')
PY

# Real Hermes directory-plugin install check. This catches the root plugin.yaml
# + __init__.py shim path used by `hermes plugins install <repo> --enable`.
if command -v hermes >/dev/null 2>&1 && command -v git >/dev/null 2>&1; then
  tmp="$(mktemp -d)"
  repo="$tmp/repo"
  home="$tmp/home"
  export SRC_ROOT="$(pwd)"
  export TEST_REPO="$repo"
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
  HERMES_HOME="$home" hermes plugins install "file://$repo" --force --enable >/dev/null
  HERMES_HOME="$home" hermes agy status >/dev/null
  echo 'directory plugin install ok'
fi
