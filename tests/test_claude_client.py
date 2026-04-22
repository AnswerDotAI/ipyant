import json

import ipyai.claude_client as cc


async def _aiter(*items):
    for o in items: yield o


def _write(tmp_path, name, *objs):
    p = tmp_path/name
    p.write_text("".join(json.dumps(o) + "\n" for o in objs))
    return p


def test_session_belongs_to_us_matches_any_session_id(tmp_path):
    p = _write(tmp_path, "a.jsonl", dict(sessionId="abc", type="user"), dict(sessionId="abc", type="assistant"))
    assert cc._session_belongs_to_us(p, {"abc"}) is True
    assert cc._session_belongs_to_us(p, {"xyz"}) is False


def test_session_belongs_to_us_empty_or_bad_file(tmp_path):
    empty = tmp_path/"empty.jsonl"
    empty.write_text("")
    bad = tmp_path/"bad.jsonl"
    bad.write_text("not json\n")
    assert cc._session_belongs_to_us(empty, {"abc"}) is False
    assert cc._session_belongs_to_us(bad, {"abc"}) is False


def test_ai_title_stub_identifies_title_only_file(tmp_path):
    stub = _write(tmp_path, "stub.jsonl", dict(type="ai-title", aiTitle="x", sessionId="z"))
    mixed = _write(tmp_path, "mixed.jsonl", dict(type="ai-title", sessionId="z"), dict(type="user", sessionId="z"))
    assert cc._is_ai_title_stub(stub) is True
    assert cc._is_ai_title_stub(mixed) is False


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
