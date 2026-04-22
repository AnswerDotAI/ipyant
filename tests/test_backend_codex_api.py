import asyncio
from pathlib import Path

import pytest

from ipyai.backends import BACKEND_CODEX_API
from tests.test_backends import _run_roundtrip


def test_codex_api_backend_roundtrip(shell, tmp_path):
    if not Path("~/.codex/auth.json").expanduser().exists(): pytest.skip("~/.codex/auth.json not present")
    asyncio.run(_run_roundtrip(type(shell), tmp_path, BACKEND_CODEX_API))
