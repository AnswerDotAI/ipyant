import argparse, asyncio, inspect, json, os, shutil
from dataclasses import asdict, is_dataclass
from pathlib import Path

from claude_agent_sdk import (AssistantMessage, ClaudeAgentOptions, ClaudeSDKClient, ResultMessage, StreamEvent, TextBlock
    ToolResultBlock, ToolUseBlock, UserMessage, create_sdk_mcp_server, tool)
from toolslm.funccall import get_schema_nm


ROOT = Path(__file__).resolve().parents[1]
CONFIG_DIR = ROOT/"samples"/".claude"


def multiply_impl(a: int, b: int) -> int:
    "Multiply two integers."
    return a * b


def make_sdk_tool(name, ns):
    fn = ns[name]
    schema = get_schema_nm(name, ns)

    @tool(schema["name"], schema["description"], schema["input_schema"])
    async def _sdk_tool(args):
        try:
            res = fn(**args)
            if inspect.isawaitable(res): res = await res
            text = res if isinstance(res, str) else json.dumps(res, ensure_ascii=False, default=str)
            return dict(content=[dict(type="text", text=text)])
        except Exception as e: return dict(content=[dict(type="text", text=f"Error: {e}")], is_error=True)

    return schema, _sdk_tool


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


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", default="haiku")
    parser.add_argument("--reset-config", action="store_true")
    args = parser.parse_args()
    if args.reset_config and CONFIG_DIR.exists(): shutil.rmtree(CONFIG_DIR)
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    os.environ["CLAUDE_CONFIG_DIR"] = str(CONFIG_DIR)

    ns = {"multiply": multiply_impl}
    schema,sdk_tool = make_sdk_tool("multiply", ns)
    server = create_sdk_mcp_server("samples", tools=[sdk_tool])
    options = ClaudeAgentOptions(model=args.model, cwd=str(ROOT), include_partial_messages=True, system_prompt="Use the tool.",
        tools=[], allowed_tools=[f"mcp__samples__{schema['name']}"], mcp_servers={"samples": server})
    prompt = "Use the multiply tool to calculate 6 * 7. After using it, reply with exactly: done"
    msgs = []
    async with ClaudeSDKClient(options=options) as client:
        await client.query(prompt)
        async for message in client.receive_response(): msgs.append(dict(summary=_summary(message), raw=_normalize(message)))

    assistant_tools = [b for m in msgs if m["summary"]["kind"]=="assistant" for b in m["summary"].get("blocks", []) if b.get("type")=="tool_use"]
    user_results = [b for m in msgs if m["summary"]["kind"]=="user" for b in m["summary"].get("blocks", [])]
    text = "".join(b.get("text", "") for m in msgs if m["summary"]["kind"]=="assistant" for b in m["summary"].get("blocks", [])
        if b.get("type")=="text").strip()
    if not assistant_tools: raise RuntimeError("No tool_use block observed")
    if not user_results: raise RuntimeError("No tool_result block observed")
    if "done" not in text.lower(): raise RuntimeError(f"Expected final assistant text to contain 'done', got: {text!r}")

    print(json.dumps(dict(schema=schema, tool_uses=assistant_tools, tool_results=user_results, final_text=text), indent=2, ensure_ascii=False))


if __name__=="__main__": asyncio.run(main())
