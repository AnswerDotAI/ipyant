import os,sys

from IPython import start_ipython
from ipythonng.cli import parse_flags

_HELP = """usage: ipyai [-h] [-b BACKEND] [-r [ID]] [-l FILE] [-p]

AI-powered IPython shell

options:
  -h, --help  show this help message and exit
  -b BACKEND  backend: claude-sdk (default), claude-api, codex, pi
  -r [ID]     resume session (no ID = pick from list)
  -l FILE     load notebook (.ipynb)
  -p          start in prompt mode"""


def main():
    if "-h" in sys.argv[1:] or "--help" in sys.argv[1:]:
        print(_HELP)
        return
    if not os.environ.get("ANTHROPIC_API_KEY") and os.environ.get("ANTHROPIC_KEY"):
        os.environ["ANTHROPIC_API_KEY"] = os.environ["ANTHROPIC_KEY"]
    _, ipython_args = parse_flags()
    start_ipython(argv=["--ext", "ipythonng", "--ext", "safepyrun", "--ext", "ipyai", "--HistoryManager.db_log_output=True", "--no-confirm-exit", "--no-banner",
        *ipython_args])
