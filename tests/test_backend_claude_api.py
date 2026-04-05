import asyncio, os

import pytest

from ipyai.backends import BACKEND_CLAUDE_API
from tests.test_backends import _run_roundtrip


def test_claude_api_backend_roundtrip(shell, tmp_path):
    key = os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_KEY")
    if not key: pytest.skip("ANTHROPIC_API_KEY/ANTHROPIC_KEY not set")
    os.environ["ANTHROPIC_API_KEY"] = key
    asyncio.run(_run_roundtrip(type(shell), tmp_path, BACKEND_CLAUDE_API))
