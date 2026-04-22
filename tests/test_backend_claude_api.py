import os

import pytest

from ipyai.backends import BACKEND_CLAUDE_API
from tests.conftest import DummyShell
from tests.test_backends import _run_roundtrip


def test_claude_api_backend_roundtrip(tmp_path, kernel_bridge, kernel_loop):
    key = os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_KEY")
    if not key: pytest.skip("ANTHROPIC_API_KEY/ANTHROPIC_KEY not set")
    os.environ["ANTHROPIC_API_KEY"] = key
    kernel_loop.run_until_complete(_run_roundtrip(DummyShell, tmp_path, BACKEND_CLAUDE_API, kernel_bridge, kernel_loop))
