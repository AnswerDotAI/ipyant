from pathlib import Path

import pytest

from ipyai.backends import BACKEND_CODEX_API
from tests.conftest import DummyShell
from tests.test_backends import _run_roundtrip


def test_codex_api_backend_roundtrip(tmp_path, kernel_bridge, kernel_loop):
    if not Path("~/.codex/auth.json").expanduser().exists(): pytest.skip("~/.codex/auth.json not present")
    kernel_loop.run_until_complete(_run_roundtrip(DummyShell, tmp_path, BACKEND_CODEX_API, kernel_bridge, kernel_loop))
