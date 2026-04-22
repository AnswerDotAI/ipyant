import asyncio

import ipyai.codex_client as cc
from ipyai.backend_common import COMPLETION_THINK


async def _aiter(*items):
    for o in items: yield o


def test_tool_name_strips_mcp_prefix():
    assert cc._tool_name("mcp__ipy__pyrun") == "pyrun"
    assert cc._tool_call("mcp__ipy__pyrun", dict(code="1+1")) == "pyrun(code='1+1')"


def test_compact_tool_leaves_blank_line_after_summary():
    text = cc._compact_tool("mcp__ipy__pyrun", dict(code="1+1"), "2")

    assert text == "\n\n🔧 pyrun(code='1+1') => 2\n\n"


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


async def test_async_stream_formatter_shows_live_tool_and_stores_compact_summary():
    fmt = cc.AsyncStreamFormatter()
    fmt.is_tty = True
    seen = []
    done = dict(kind="tool_complete", name="mcp__ipy__pyrun", input=dict(code="1+1"), content="2")
    stream = _aiter(dict(kind="tool_start", name="mcp__ipy__pyrun", input=dict(code="1+1")), done, "2")

    async for _ in fmt.format_stream(stream): seen.append(fmt.display_text)

    assert seen[0] == "⌛ `pyrun(code='1+1')`"
    assert "🔧 pyrun(code='1+1') => 2\n\n2" in fmt.final_text
    assert seen[-1].endswith("\n\n2")


async def test_complete_uses_toolless_ephemeral_turn(shell, monkeypatch):
    fake = FakeCodexClient()
    monkeypatch.setattr(cc, "get_codex_client", lambda: fake)
    backend = cc.CodexBackend(shell=shell, system_prompt="system")

    res = await backend.complete("hi", model="gpt-5.4-mini")

    assert str(res) == "done"
    assert fake.started == [dict(model="gpt-5.4-mini", sp="system", dynamic_tools=None, ephemeral=True, cwd=backend.ctx.cwd)]
    assert fake.turns == [(("thread_1", "hi"), dict(ns={}, think=COMPLETION_THINK, cwd=backend.ctx.cwd))]


async def test_consume_turn_emits_tool_start_and_complete_events():
    client = cc._CodexAppServer()
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
