#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
export XDG_CONFIG_HOME="${ROOT}/.tmp/xdg"
mkdir -p "${XDG_CONFIG_HOME}"

cd "${ROOT}"
python samples/capture_sdk_shapes.py "$@"
