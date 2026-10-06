#!/bin/bash
# EQ Recorder: Dock app (one window, AppKit).
# Uses the project's own venv (.venv), never the system/Homebrew python3,
# so the installed packages match requirements.txt exactly.
cd "$(dirname "$0")"
PY=".venv/bin/python3.10"
if [ ! -x "$PY" ]; then
  echo "✗ Немає venv: $PY" >&2
  echo "  Створи його: /opt/homebrew/bin/python3.10 -m venv .venv && .venv/bin/pip install -r requirements.txt" >&2
  exit 1
fi
exec "$PY" app/recorder.py "$@"
