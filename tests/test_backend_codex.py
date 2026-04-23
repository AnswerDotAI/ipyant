import shutil

import pytest

import ipyai.codex_client as codex
from ipyai.backends import BACKEND_CODEX
from tests.conftest import DummyShell
from tests.test_backends import _run_roundtrip


def test_codex_backend_roundtrip(tmp_path, kernel_bridge, kernel_loop):
    if shutil.which("codex") is None: pytest.skip("codex CLI is not available")
    client = codex.get_codex_client()
    before = set(client.created_thread_ids)
    try: kernel_loop.run_until_complete(_run_roundtrip(DummyShell, tmp_path, BACKEND_CODEX, kernel_bridge, kernel_loop))
    finally:
        created = set(client.created_thread_ids) - before
        if created: kernel_loop.run_until_complete(client.archive_threads(created))
