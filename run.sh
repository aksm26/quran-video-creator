#!/usr/bin/env bash
# Starts Quran Video Creator. Works from any folder, e.g. ./run.sh or by double-clicking it.
cd "$(dirname "$(readlink -f "$0")")" || exit 1
if [ ! -x .venv/bin/python ]; then
    echo "First-time setup: creating the virtual environment..."
    # On failure, remove the half-made environment so the next start tries again from scratch.
    python3 -m venv .venv && .venv/bin/pip install -r requirements.txt || { rm -rf .venv; exit 1; }
fi
exec .venv/bin/python main.py "$@"
