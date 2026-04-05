import asyncio, shutil

import pytest

from ipyai.backends import BACKEND_CLAUDE_SDK
from tests.test_backends import _run_roundtrip


def test_claude_sdk_backend_roundtrip(shell, tmp_path):
    if shutil.which("claude") is None: pytest.skip("claude CLI is not available")
    asyncio.run(_run_roundtrip(type(shell), tmp_path, BACKEND_CLAUDE_SDK))
