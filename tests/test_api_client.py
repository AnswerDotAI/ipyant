import asyncio

from litellm.types.utils import Choices, Message, ModelResponse

from ipyai.api_client import AsyncStreamFormatter


def _resp_with_tc(call_id="call_1", name="pyrun", arguments='{"code":"2+2"}'):
    msg = Message(role="assistant", content=None,
        tool_calls=[{"id": call_id, "type": "function", "function": {"name": name, "arguments": arguments}}])
    return ModelResponse(choices=[Choices(message=msg, index=0, finish_reason="tool_calls")])


async def _run(items):
    fmt = AsyncStreamFormatter()
    out = []

    async def _agen():
        for x in items: yield x

    async for chunk in fmt.format_stream(_agen()): out.append(chunk)
    return fmt, out


def test_tool_start_marker_suppressed():
    fmt,out = asyncio.run(_run([_resp_with_tc()]))
    assert out == [""]
    assert "⏳" not in fmt.outp
    assert "call_1" in fmt.tcs


def test_tool_result_rendered_as_compact_line():
    resp = _resp_with_tc(call_id="call_1", name="pyrun", arguments='{"code":"2+2"}')
    tool_msg = {"tool_call_id": "call_1", "content": "4"}
    fmt,out = asyncio.run(_run([resp, tool_msg]))
    joined = "".join(out)
    assert "🔧 pyrun(code='2+2') => 4" in joined
    assert "<details>" not in joined
    assert "<summary>" not in joined
    assert "```json" not in joined
