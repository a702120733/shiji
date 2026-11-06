#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
runtime="${SHIJI_VENV:-$PWD/.venv}"
if [[ ! -x "$runtime/bin/python" ]]; then
  if command -v uv >/dev/null 2>&1; then
    uv venv --python 3.12 "$runtime"
  else
    if ! command -v python3.12 >/dev/null 2>&1; then
      echo '需要 Python 3.12，或安装 uv 后重试。' >&2
      exit 1
    fi
    python3.12 -m venv "$runtime"
  fi
fi
if [[ ! -f "$runtime/.deps-ready" ]]; then
  if command -v uv >/dev/null 2>&1; then
    uv pip install --python "$runtime/bin/python" -r shiji/requirements.txt
  else
    "$runtime/bin/python" -m pip install -r shiji/requirements.txt
  fi
  touch "$runtime/.deps-ready"
fi
if [[ "$(uname -s)" == Darwin ]]; then
  default_data="$HOME/Library/Application Support/Shiji/data"
else
  default_data="$PWD/data"
fi
exec "$runtime/bin/python" shiji/app.py --data-dir "${SHIJI_DATA_DIR:-$default_data}" --port "${SHIJI_PORT:-8879}"
