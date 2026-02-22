#!/usr/bin/env bash
# White Light trading pipeline entry point.
# Called by cron (local) or EventBridge/Lambda (AWS).
#
# Usage:
#   ./scripts/run.sh                 # Normal execution
#   ./scripts/run.sh --dry-run       # Strategy only, no orders
#   WL_DEPLOYMENT_MODE=paper ./scripts/run.sh  # Paper trading

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

# Activate virtual environment if present
if [ -f "$PROJECT_DIR/.venv/bin/activate" ]; then
    source "$PROJECT_DIR/.venv/bin/activate"
fi

# Run the pipeline
cd "$PROJECT_DIR"
exec python -m whitelight run "$@"
