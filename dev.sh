#!/usr/bin/env bash
# dev.sh — Start the Audible Downloader locally for testing

set -e

cd "$(dirname "$0")"

PORT="${PORT:-5505}"
export FLASK_ENV=development

echo "Starting Audible Downloader on http://localhost:${PORT}"
uv run python run.py
