import os

from IPython import start_ipython
from ipythonng.cli import parse_flags

from .backends import BACKEND_CLAUDE_API, BACKEND_CODEX, DEFAULT_BACKEND


def main(default_backend=DEFAULT_BACKEND, prog_name="ipyai"):
    os.environ["IPYAI_DEFAULT_BACKEND"] = default_backend
    os.environ["IPYAI_ENTRYPOINT"] = prog_name
    _, ipython_args = parse_flags()
    start_ipython(argv=["--ext", "ipythonng", "--ext", "safepyrun", "--ext", "ipyai", "--HistoryManager.db_log_output=True", "--no-confirm-exit", "--no-banner",
        *ipython_args])


def ipyclaude_main(): main(BACKEND_CLAUDE_API, "ipyclaude")


def ipycodex_main(): main(BACKEND_CODEX, "ipycodex")
