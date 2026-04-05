from IPython import start_ipython
from ipythonng.cli import parse_flags


def main():
    _, ipython_args = parse_flags()
    start_ipython(argv=["--ext", "ipythonng", "--ext", "safepyrun", "--ext", "ipyant", "--HistoryManager.db_log_output=True", "--no-confirm-exit", "--no-banner",
        *ipython_args])
