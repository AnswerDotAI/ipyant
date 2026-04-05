#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
export CLAUDE_CONFIG_DIR="${ROOT}/.tmp/claude-test"
export XDG_CONFIG_HOME="${ROOT}/.tmp/xdg"
mkdir -p "${CLAUDE_CONFIG_DIR}"
mkdir -p "${XDG_CONFIG_HOME}"

cd "${ROOT}"
pytest "$@"
