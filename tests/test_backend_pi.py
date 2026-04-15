import asyncio, shutil

import pytest

from ipyai.backends import BACKEND_PI
from tests.test_backends import _run_roundtrip


def test_pi_backend_roundtrip(shell, tmp_path):
    if shutil.which("pi") is None: pytest.skip("pi CLI is not available")
    asyncio.run(_run_roundtrip(type(shell), tmp_path, BACKEND_PI))
