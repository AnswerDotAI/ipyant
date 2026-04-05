from claude_agent_sdk import get_session_messages
from IPython.core.interactiveshell import InteractiveShell
from mcp.types import CallToolRequest, CallToolRequestParams
from safepyrun import RunPython

from ipyant.claude_client import AsyncStreamFormatter, ClaudeBackend, write_synthetic_session


async def _aiter(*items):
    for item in items: yield item


async def test_async_stream_formatter_tracks_thinking_and_tools():
    fmt = AsyncStreamFormatter()
    fmt.is_tty = True
    seen = []
    stream = _aiter(dict(kind="thinking_start"), dict(kind="thinking_delta", delta="hmm"), dict(kind="thinking_end"),
        dict(kind="tool_start", id="1", name="python", input={"code": "6*7"}),
        dict(kind="tool_complete", id="1", name="python", input={"code": "6*7"}, content="42", is_error=False), "done")
    async for _ in fmt.format_stream(stream): seen.append(fmt.display_text)

    assert any("> hmm" in o for o in seen)
    assert "🔧 python(code='6*7') => 42" in fmt.final_text
    assert fmt.final_text.endswith("done")


def test_write_synthetic_session_roundtrips_through_sdk(tmp_path):
    info = write_synthetic_session(tmp_path, [("<user-request>Pick a number</user-request>", "60")])
    msgs = get_session_messages(info.session_id, directory=str(tmp_path))
    assert msgs[0].message["content"] == "<user-request>Pick a number</user-request>"
    assert msgs[1].message["content"][0]["text"] == "60"


async def test_python_tool_delegates_to_real_pyrun():
    InteractiveShell.clear_instance()
    try:
        shell = InteractiveShell.instance()
        shell.user_ns["pyrun"] = RunPython(g=shell.user_ns)
        backend = ClaudeBackend(shell=shell)
        server = backend._sdk_server()["instance"]
        handler = server.request_handlers[CallToolRequest]

        await handler(CallToolRequest(method="tools/call", params=CallToolRequestParams(name="python", arguments={"code": "x = 1"})))
        result = await handler(CallToolRequest(method="tools/call", params=CallToolRequestParams(name="python", arguments={"code": "x + 1"})))

        assert result.root.isError is False
        assert result.root.content[0].text == "2"
        assert shell.user_ns["x"] == 1
    finally: InteractiveShell.clear_instance()
