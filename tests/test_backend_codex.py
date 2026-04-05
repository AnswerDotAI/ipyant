import asyncio, shutil

import pytest

from ipyai.backends import BACKEND_CODEX
from tests.test_backends import _run_roundtrip


def test_codex_backend_roundtrip(shell, tmp_path):
    if shutil.which("codex") is None: pytest.skip("codex CLI is not available")
    asyncio.run(_run_roundtrip(type(shell), tmp_path, BACKEND_CODEX))
