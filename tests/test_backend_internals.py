"Fast backend-internal unit tests: api_client formatter overrides, Claude CLI backend internals, Codex backend internals, MCP socket server."
import asyncio, json

from litellm.types.utils import Choices, Message, ModelResponse
from safepyrun import RunPython

import ipyai.claude_client as claude
import ipyai.codex_client as codex
from ipyai.api_client import AsyncStreamFormatter
from ipyai.backend_common import COMPLETION_THINK
from ipyai.mcp_server import ToolSocketServer
from ipyai.tooling import ToolRegistry


# ---- api_client (lisette formatter overrides) ----

def _resp_with_tc(call_id="call_1", name="pyrun", arguments='{"code":"2+2"}'):
    msg = Message(role="assistant", content=None,
        tool_calls=[dict(id=call_id, type="function", function=dict(name=name, arguments=arguments))])
    return ModelResponse(choices=[Choices(message=msg, index=0, finish_reason="tool_calls")])


async def _run_api(items):
    fmt = AsyncStreamFormatter()
    out = []

    async def _agen():
        for x in items: yield x

    async for chunk in fmt.format_stream(_agen()): out.append(chunk)
    return fmt, out


def test_api_tool_start_marker_suppressed():
    fmt,out = asyncio.run(_run_api([_resp_with_tc()]))
    assert out == [""]
    assert "⏳" not in fmt.outp
    assert "call_1" in fmt.tcs


def test_api_tool_result_rendered_as_compact_line():
    resp = _resp_with_tc(call_id="call_1", name="pyrun", arguments='{"code":"2+2"}')
    tool_msg = {"tool_call_id": "call_1", "content": "4"}
    fmt,out = asyncio.run(_run_api([resp, tool_msg]))
    joined = "".join(out)
    assert "🔧 pyrun(code='2+2') => 4" in joined
    assert "<details>" not in joined
    assert "<summary>" not in joined
    assert "```json" not in joined


# ---- claude_client (jsonl cleanup predicates + formatter) ----

async def _aiter(*items):
    for o in items: yield o


def _jsonl(tmp_path, name, *objs):
    p = tmp_path/name
    p.write_text("".join(json.dumps(o) + "\n" for o in objs))
    return p


def test_session_belongs_to_us_matches_any_session_id(tmp_path):
    p = _jsonl(tmp_path, "a.jsonl", dict(sessionId="abc", type="user"), dict(sessionId="abc", type="assistant"))
    assert claude._session_belongs_to_us(p, {"abc"}) is True
    assert claude._session_belongs_to_us(p, {"xyz"}) is False


def test_session_belongs_to_us_empty_or_bad_file(tmp_path):
    empty = tmp_path/"empty.jsonl"
    empty.write_text("")
    bad = tmp_path/"bad.jsonl"
    bad.write_text("not json\n")
    assert claude._session_belongs_to_us(empty, {"abc"}) is False
    assert claude._session_belongs_to_us(bad, {"abc"}) is False


def test_ai_title_stub_identifies_title_only_file(tmp_path):
    stub = _jsonl(tmp_path, "stub.jsonl", dict(type="ai-title", aiTitle="x", sessionId="z"))
    mixed = _jsonl(tmp_path, "mixed.jsonl", dict(type="ai-title", sessionId="z"), dict(type="user", sessionId="z"))
    assert claude._is_ai_title_stub(stub) is True
    assert claude._is_ai_title_stub(mixed) is False


def test_claude_tool_name_strips_mcp_prefix():
    assert claude._tool_name("mcp__ipy__pyrun") == "pyrun"
    assert claude._tool_call("mcp__ipy__pyrun", dict(code="1+1")) == "pyrun(code='1+1')"


def test_claude_compact_tool_leaves_blank_line_after_summary():
    assert claude._compact_tool("mcp__ipy__pyrun", dict(code="1+1"), "2") == "\n\n🔧 pyrun(code='1+1') => 2\n\n"


async def test_claude_async_stream_formatter_shows_live_tool_and_stores_compact_summary():
    fmt = claude.AsyncStreamFormatter()
    fmt.is_tty = True
    seen = []
    done = dict(kind="tool_complete", name="mcp__ipy__pyrun", input=dict(code="1+1"), content="2")
    stream = _aiter(dict(kind="tool_start", name="mcp__ipy__pyrun", input=dict(code="1+1")), done, "2")

    async for _ in fmt.format_stream(stream): seen.append(fmt.display_text)

    assert seen[0] == "⌛ `pyrun(code='1+1')`"
    assert "🔧 pyrun(code='1+1') => 2\n\n2" in fmt.final_text
    assert seen[-1].endswith("\n\n2")


# ---- codex_client (formatter + complete path + turn consumer) ----

class FakeCodexClient:
    def __init__(self):
        self.started = []
        self.turns = []

    async def start_thread(self, **kwargs):
        self.started.append(kwargs)
        return "thread_1"

    async def turn_stream(self, *args, **kwargs):
        self.turns.append((args, kwargs))
        yield "done"


def test_codex_tool_name_strips_mcp_prefix():
    assert codex._tool_name("mcp__ipy__pyrun") == "pyrun"
    assert codex._tool_call("mcp__ipy__pyrun", dict(code="1+1")) == "pyrun(code='1+1')"


def test_codex_compact_tool_leaves_blank_line_after_summary():
    assert codex._compact_tool("mcp__ipy__pyrun", dict(code="1+1"), "2") == "\n\n🔧 pyrun(code='1+1') => 2\n\n"


async def test_codex_async_stream_formatter_shows_live_tool_and_stores_compact_summary():
    fmt = codex.AsyncStreamFormatter()
    fmt.is_tty = True
    seen = []
    done = dict(kind="tool_complete", name="mcp__ipy__pyrun", input=dict(code="1+1"), content="2")
    stream = _aiter(dict(kind="tool_start", name="mcp__ipy__pyrun", input=dict(code="1+1")), done, "2")

    async for _ in fmt.format_stream(stream): seen.append(fmt.display_text)

    assert seen[0] == "⌛ `pyrun(code='1+1')`"
    assert "🔧 pyrun(code='1+1') => 2\n\n2" in fmt.final_text
    assert seen[-1].endswith("\n\n2")


async def test_codex_complete_uses_toolless_ephemeral_turn(shell, monkeypatch):
    fake = FakeCodexClient()
    monkeypatch.setattr(codex, "get_codex_client", lambda: fake)
    backend = codex.CodexBackend(shell=shell, system_prompt="system")

    res = await backend.complete("hi", model="gpt-5.4-mini")

    assert str(res) == "done"
    assert fake.started == [dict(model="gpt-5.4-mini", sp="system", dynamic_tools=None, ephemeral=True, cwd=backend.ctx.cwd)]
    assert fake.turns == [(("thread_1", "hi"), dict(tools=None, think=COMPLETION_THINK, cwd=backend.ctx.cwd))]


async def test_codex_consume_turn_emits_tool_start_and_complete_events():
    client = codex._CodexAppServer()
    client.events = asyncio.Queue()
    thread_id,turn_id = "thread_1","turn_1"
    started = dict(method="item/started", params=dict(threadId=thread_id, turnId=turn_id,
        item=dict(type="dynamicToolCall", id="tool_1", tool="mcp__ipy__pyrun", arguments=dict(code="1+1"))))
    done = dict(method="item/completed", params=dict(threadId=thread_id, turnId=turn_id,
        item=dict(type="dynamicToolCall", id="tool_1", tool="mcp__ipy__pyrun", arguments=dict(code="1+1"), contentItems=[dict(type="inputText", text="2")])))
    msgs = [started, done, dict(method="turn/completed", params=dict(threadId=thread_id, turnId=turn_id, turn=dict(id=turn_id)))]
    for msg in msgs: await client.events.put(msg)

    chunks = [o async for o in client._consume_turn(thread_id, turn_id, {})]

    assert chunks == [dict(kind="tool_start", name="mcp__ipy__pyrun", input=dict(code="1+1")),
        dict(kind="tool_complete", name="mcp__ipy__pyrun", input=dict(code="1+1"), content="2")]


# ---- mcp_server (unix-socket RPC) ----

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
    srv = await ToolSocketServer(ToolRegistry.from_ns(ns)).start()
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
