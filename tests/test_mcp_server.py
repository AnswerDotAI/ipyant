import asyncio, json

import pytest

from safepyrun import RunPython

from ipyai.mcp_server import ToolSocketServer
from ipyai.tooling import ToolRegistry


async def _rpc(sock_path, method, params=None):
    reader, writer = await asyncio.open_unix_connection(sock_path)
    try:
        writer.write((json.dumps(dict(id=1, method=method, params=params or {})) + "\n").encode())
        await writer.drain()
        return json.loads(await reader.readline())
    finally:
        writer.close()
        try: await writer.wait_closed()
        except Exception: pass


async def _with_server(ns, fn):
    srv = await ToolSocketServer(ToolRegistry(ns)).start()
    try: return await fn(srv.sock_path)
    finally: await srv.stop()


def test_socket_list_tools():
    ns = {"pyrun": RunPython(g={})}
    resp = asyncio.run(_with_server(ns, lambda p: _rpc(p, "list_tools")))
    names = [o["name"] for o in resp["result"]]
    assert "pyrun" in names


def test_socket_call_tool_pyrun():
    ns = {}
    ns["pyrun"] = RunPython(g=ns)
    ns["hidden"] = "walnut"
    resp = asyncio.run(_with_server(ns, lambda p: _rpc(p, "call_tool", dict(name="pyrun", args=dict(code="hidden")))))
    assert resp["result"]["isError"] is False
    assert "walnut" in resp["result"]["content"][0]["text"]


def test_socket_unknown_method():
    resp = asyncio.run(_with_server({}, lambda p: _rpc(p, "nonsense")))
    assert "error" in resp
