#!/bin/sh
# Run the test suite in this checkout's own environment; arguments go to pytest.
set -eu
cd "$(dirname "$0")/.."
if [ ! -e .venv/installed ] || [ requirements.txt -nt .venv/installed ]; then
    [ -x .venv/bin/python ] || "${PYTHON:-python3}" -m venv .venv
    .venv/bin/pip install -q -r requirements.txt
    touch .venv/installed
fi
exec .venv/bin/python -m pytest "$@"
