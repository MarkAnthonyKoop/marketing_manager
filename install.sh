#!/usr/bin/env bash
# Install this project (and its sibling deps) into the current Python env.
set -euo pipefail

cd "$(dirname "$0")"

# Prefer pip from an already-active venv; fall back to user-pip.
if [[ -n "${VIRTUAL_ENV:-}" ]]; then
    pip install -e .
else
    pip install --user -e .
fi

echo
echo "Installed $(python3 -c 'import tomllib; print(tomllib.load(open("pyproject.toml","rb"))["project"]["name"])')."
echo "Try: python3 -m $(basename "$PWD") --help"
