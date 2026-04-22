import shutil

import pytest

from ipyai.backends import BACKEND_CLAUDE_CLI
from tests.conftest import DummyShell
from tests.test_backends import _run_roundtrip


def test_claude_cli_backend_roundtrip(tmp_path, kernel_bridge, kernel_loop):
    if shutil.which("claude") is None: pytest.skip("claude CLI is not available")
    kernel_loop.run_until_complete(_run_roundtrip(DummyShell, tmp_path, BACKEND_CLAUDE_CLI, kernel_bridge, kernel_loop))
