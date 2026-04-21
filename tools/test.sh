#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
export XDG_CONFIG_HOME="${ROOT}/.tmp/xdg"
mkdir -p "${XDG_CONFIG_HOME}"
# Claude CLI OAuth on macOS reads credentials from the login keychain keyed by the userID in ~/.claude.json;
# redirecting CLAUDE_CONFIG_DIR breaks that lookup, so we let the subprocess use the user's real config and
# rely on ClaudeBackend's per-turn cleanup sweep to remove any session files it writes during the test.

cd "${ROOT}"
pytest "$@"
