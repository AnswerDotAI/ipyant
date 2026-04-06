import ipyai.claude_client as cc


async def _aiter(*items):
    for o in items: yield o


def test_tool_name_strips_mcp_prefix():
    assert cc._tool_name("mcp__ipy__pyrun") == "pyrun"
    assert cc._tool_call("mcp__ipy__pyrun", dict(code="1+1")) == "pyrun(code='1+1')"


def test_compact_tool_leaves_blank_line_after_summary():
    text = cc._compact_tool("mcp__ipy__pyrun", dict(code="1+1"), "2")

    assert text == "\n\n🔧 pyrun(code='1+1') => 2\n\n"


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
