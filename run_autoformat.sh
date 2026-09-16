#!/usr/bin/env bash
set -euo pipefail

cd -- "$(dirname -- "${BASH_SOURCE[0]}")"
uv sync --locked
uv run --no-sync ruff check --fix .
uv run --no-sync ruff format .
