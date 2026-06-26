#!/usr/bin/env bash
# Single entrypoint for cron/launchd. Activates the venv and runs the cycle.
set -euo pipefail
cd "$(dirname "$0")"
exec .venv/bin/python update.py "$@"
