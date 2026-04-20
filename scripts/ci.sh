#!/usr/bin/env bash
# Local CI — run before committing. No GitHub Actions; this is the canonical gate.
set -euo pipefail

cd "$(dirname "$0")/.."

echo "==> ruff (lint)"
python -m ruff check src tests

echo "==> ruff (format check)"
python -m ruff format --check src tests

echo "==> mypy (typecheck)"
python -m mypy src/unitygraph

echo "==> pytest"
python -m pytest

echo "==> CI OK"
