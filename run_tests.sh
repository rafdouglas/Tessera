#!/bin/bash
# IdeoGIS test runner — invokes pytest inside QGIS flatpak
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
export PYTHONPATH="${SCRIPT_DIR}:${SCRIPT_DIR}/plugins:${PYTHONPATH:-}"

exec flatpak run --command=python3 org.qgis.qgis -m pytest "$@"
