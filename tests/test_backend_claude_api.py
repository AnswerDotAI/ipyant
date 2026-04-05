import asyncio, os

import pytest

from ipyai.backends import BACKEND_CLAUDE_API
from tests.test_backends import _run_roundtrip


def test_claude_api_backend_roundtrip(shell, tmp_path):
    if not os.environ.get("ANTHROPIC_API_KEY"): pytest.skip("ANTHROPIC_API_KEY is not set")
    asyncio.run(_run_roundtrip(type(shell), tmp_path, BACKEND_CLAUDE_API))
