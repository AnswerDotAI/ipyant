import asyncio

import ipyai.pi_client as pc


class FakeProc:
    def __init__(self, events):
        self.events = asyncio.Queue()
        for o in events: self.events.put_nowait(o)

    async def request(self, *_args, **_kwargs):
        return dict(type="response", success=True)


async def test_stream_prompt_maps_text_thinking_and_bash_delta(shell):
    backend = pc.PiBackend(shell=shell, system_prompt="sys")
    events = [
        dict(type="message_update", assistantMessageEvent=dict(type="thinking_start")),
        dict(type="message_update", assistantMessageEvent=dict(type="thinking_delta", delta="plan")),
        dict(type="message_update", assistantMessageEvent=dict(type="thinking_end")),
        dict(type="message_update", assistantMessageEvent=dict(type="text_delta", delta="Hello")),
        dict(type="tool_execution_start", toolCallId="t1", toolName="bash", args=dict(command="echo hi")),
        dict(type="tool_execution_update", toolCallId="t1", toolName="bash", args=dict(command="echo hi"),
            partialResult=dict(content=[dict(type="text", text="a")])) ,
        dict(type="tool_execution_update", toolCallId="t1", toolName="bash", args=dict(command="echo hi"),
            partialResult=dict(content=[dict(type="text", text="ab")])) ,
        dict(type="tool_execution_end", toolCallId="t1", toolName="bash", isError=False,
            result=dict(content=[dict(type="text", text="ab")], details=dict(exitCode=0))),
        dict(type="agent_end"),
    ]

    out = [o async for o in backend._stream_prompt(FakeProc(events), "hi")]

    assert out == [
        dict(kind="thinking_start"),
        dict(kind="thinking_delta", delta="plan"),
        dict(kind="thinking_end"),
        "Hello",
        dict(kind="command_start", id="t1", command="echo hi", cwd=backend.ctx.cwd),
        dict(kind="command_delta", id="t1", delta="a", command="echo hi", cwd=backend.ctx.cwd),
        dict(kind="command_delta", id="t1", delta="b", command="echo hi", cwd=backend.ctx.cwd),
        dict(kind="command_complete", id="t1", command="echo hi", output="ab", exit_code=0),
    ]


def test_pi_cmd_supports_ephemeral_and_extensions():
    cmd = pc._pi_cmd("sonnet", session="/tmp/s.jsonl", ephemeral=False, system_prompt="sys", extension="/tmp/ext.ts", tool_mode="on")
    assert "--mode" in cmd and "rpc" in cmd
    assert "--session" in cmd and "/tmp/s.jsonl" in cmd
    assert "--system-prompt" in cmd and "sys" in cmd
    assert "-e" in cmd and "/tmp/ext.ts" in cmd
    assert "--no-tools" in cmd

    cmd2 = pc._pi_cmd("haiku", ephemeral=True, tool_mode="off")
    assert "--no-session" in cmd2
    assert "--no-tools" in cmd2
