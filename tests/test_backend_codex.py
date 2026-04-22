import shutil

import pytest

from ipyai.backends import BACKEND_CODEX
from tests.conftest import DummyShell
from tests.test_backends import _run_roundtrip


def test_codex_backend_roundtrip(tmp_path, kernel_bridge, kernel_loop):
    if shutil.which("codex") is None: pytest.skip("codex CLI is not available")
    kernel_loop.run_until_complete(_run_roundtrip(DummyShell, tmp_path, BACKEND_CODEX, kernel_bridge, kernel_loop))
