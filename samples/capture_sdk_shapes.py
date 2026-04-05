import argparse, asyncio, json, os, shutil
from dataclasses import asdict, is_dataclass
from pathlib import Path

from claude_agent_sdk import AssistantMessage, ClaudeAgentOptions, ClaudeSDKClient, ResultMessage, StreamEvent, TextBlock
from claude_agent_sdk import ToolResultBlock, ToolUseBlock, UserMessage, create_sdk_mcp_server, tool


ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = ROOT/"samples"/"outputs"
CONFIG_DIR = ROOT/"samples"/".claude"


def _normalize(obj):
    if is_dataclass(obj): return {k:_normalize(v) for k,v in asdict(obj).items()}
    if isinstance(obj, Path): return str(obj)
    if isinstance(obj, list): return [_normalize(o) for o in obj]
    if isinstance(obj, dict): return {k:_normalize(v) for k,v in obj.items()}
    return obj


def _summary(message):
    if isinstance(message, StreamEvent):
        event = message.event
        delta = event.get("delta", {})
        return dict(kind="stream", type=event.get("type"), delta_type=delta.get("type"), text=delta.get("text"), thinking=delta.get("thinking"))
    if isinstance(message, AssistantMessage):
        blocks = []
        for block in message.content:
            if isinstance(block, TextBlock): blocks.append(dict(type="text", text=block.text))
            elif isinstance(block, ToolUseBlock): blocks.append(dict(type="tool_use", id=block.id, name=block.name, input=block.input))
            else: blocks.append(dict(type=type(block).__name__))
        return dict(kind="assistant", session_id=message.session_id, stop_reason=message.stop_reason, blocks=blocks)
    if isinstance(message, UserMessage):
        blocks = message.content if isinstance(message.content, list) else []
        return dict(kind="user", blocks=[dict(type="tool_result", tool_use_id=b.tool_use_id, is_error=b.is_error, content=b.content)
            for b in blocks if isinstance(b, ToolResultBlock)])
    if isinstance(message, ResultMessage):
        return dict(kind="result", session_id=message.session_id, stop_reason=message.stop_reason, is_error=message.is_error, result=message.result)
    return dict(kind=type(message).__name__)


async def _collect(options, prompt):
    msgs = []
    async with ClaudeSDKClient(options=options) as client:
        await client.query(prompt)
        async for message in client.receive_response(): msgs.append(dict(summary=_summary(message), raw=_normalize(message)))
    return msgs


@tool("python", "Execute a tiny expression evaluator", {"code": str})
async def python_tool(args):
    code = args["code"].strip()
    result = eval(code, {"__builtins__": {}}, {})
    return {"content": [{"type": "text", "text": repr(result)}]}


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--reset-config", action="store_true")
    args = parser.parse_args()
    if args.reset_config and CONFIG_DIR.exists(): shutil.rmtree(CONFIG_DIR)
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    os.environ["CLAUDE_CONFIG_DIR"] = str(CONFIG_DIR)

    text_options = ClaudeAgentOptions(model="haiku", cwd=str(ROOT), include_partial_messages=True, system_prompt="", tools=[])
    tool_server = create_sdk_mcp_server("samples", tools=[python_tool])
    tool_options = ClaudeAgentOptions(model="haiku", cwd=str(ROOT), include_partial_messages=True, mcp_servers={"samples": tool_server},
        system_prompt="Use the python tool when arithmetic is requested.", tools=[], allowed_tools=["mcp__samples__python"])
    captures = dict(text_stream_json=await _collect(text_options, "Reply with exactly: alpha beta"),
        python_tool_stream_json=await _collect(tool_options, "Use python to evaluate 6*7, then reply with exactly: done"))
    for name,data in captures.items():
        path = OUT_DIR/name.replace("_json", ".json")
        path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


if __name__ == "__main__": asyncio.run(main())
