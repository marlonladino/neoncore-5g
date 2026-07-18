#!/usr/bin/env bash
# Launch the NeonCore 5G control center TUI.
set -euo pipefail
cd "$(dirname "$0")"

if [ ! -d .venv ]; then
  echo "Creating virtualenv (.venv) and installing dependencies..."
  python3 -m venv .venv
  .venv/bin/pip install -q --upgrade pip
  .venv/bin/pip install -q -r requirements.txt
fi

exec .venv/bin/python -m neoncore_cli
