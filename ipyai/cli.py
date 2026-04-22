import sys

from .app import main as _main


__all__ = ["main", "main_claude", "main_codex"]


def _has_backend_flag(argv):
    return any(a == "-b" or a.startswith("-b=") or a == "--backend" or a.startswith("--backend=")
        or a.startswith("--IPyAIApp.backend") for a in argv)


def _default_backend(argv, backend):
    "Return argv with `-b <backend>` prepended if no backend flag was explicitly supplied."
    return argv if _has_backend_flag(argv) else ["-b", backend, *argv]


def main(): _main()


def main_claude():
    sys.argv = [sys.argv[0], *_default_backend(sys.argv[1:], "claude-api")]
    _main()


def main_codex():
    sys.argv = [sys.argv[0], *_default_backend(sys.argv[1:], "codex-api")]
    _main()
