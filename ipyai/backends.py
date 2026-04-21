from dataclasses import dataclass

from .api_client import ClaudeAPIBackend
from .claude_client import ClaudeBackend
from .codex_client import CodexBackend

BACKEND_CLAUDE_CLI = "claude-cli"
BACKEND_CLAUDE_API = "claude-api"
BACKEND_CODEX = "codex"
DEFAULT_BACKEND = BACKEND_CODEX
BACKEND_ALIASES = {"claude": BACKEND_CLAUDE_CLI, "cli": BACKEND_CLAUDE_CLI, "claude-cli": BACKEND_CLAUDE_CLI,
    "api": BACKEND_CLAUDE_API, "claude-api": BACKEND_CLAUDE_API, "codex": BACKEND_CODEX}


@dataclass(frozen=True)
class BackendSpec:
    name: str
    label: str
    factory: type
    default_model: str
    default_completion_model: str


BACKENDS = {BACKEND_CLAUDE_CLI: BackendSpec(BACKEND_CLAUDE_CLI, "Claude CLI", ClaudeBackend, "sonnet", "haiku"),
    BACKEND_CLAUDE_API: BackendSpec(BACKEND_CLAUDE_API, "Claude API", ClaudeAPIBackend, "claude-sonnet-4-6", "claude-haiku-4-5-20251001"),
    BACKEND_CODEX: BackendSpec(BACKEND_CODEX, "Codex", CodexBackend, "gpt-5.4", "gpt-5.4-mini")}


def normalize_backend_name(name=None):
    key = (name or DEFAULT_BACKEND).strip().lower()
    if key in BACKENDS: return key
    if key in BACKEND_ALIASES: return BACKEND_ALIASES[key]
    choices = ", ".join(BACKENDS)
    raise ValueError(f"Unknown backend {name!r}. Expected one of: {choices}")


def backend_spec(name=None): return BACKENDS[normalize_backend_name(name)]
