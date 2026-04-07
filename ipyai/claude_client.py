import json, uuid
from collections.abc import Iterable
from datetime import datetime, timedelta, timezone
from pathlib import Path

from claude_agent_sdk import AssistantMessage, ClaudeAgentOptions, ClaudeSDKClient, ResultMessage, StreamEvent
from claude_agent_sdk import ToolResultBlock, ToolUseBlock, UserMessage, create_sdk_mcp_server, tool
from claude_agent_sdk._internal.sessions import _get_project_dir

from .backend_common import (BaseBackend, CommonStreamFormatter, ConversationSeed, compact_tool, effort_level,
    replayable_assistant_text, strip_thinking, tool_call, tool_name)


BUILTIN_TOOLS = ["Bash", "Edit", "Read", "Skill", "WebFetch", "WebSearch", "Write"]


def _iso(ts): return ts.replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _stringify_content(content):
    if content is None: return ""
    if isinstance(content, str): return content
    parts = []
    for item in content:
        if isinstance(item, dict) and item.get("type") == "text": parts.append(item.get("text", ""))
        else: parts.append(json.dumps(item, ensure_ascii=False, default=str))
    return "\n".join(o for o in parts if o)


AsyncStreamFormatter = CommonStreamFormatter
_tool_name,_tool_call,_compact_tool = tool_name,tool_call,compact_tool


def write_synthetic_session(project_root: str | Path, turns: Iterable, session_id: str | None=None):
    project_root = Path(project_root).resolve()
    session_id = session_id or str(uuid.uuid4())
    project_dir = _get_project_dir(str(project_root))
    project_dir.mkdir(parents=True, exist_ok=True)
    path = project_dir / f"{session_id}.jsonl"
    turns = list(turns)
    now = datetime.now(timezone.utc) - timedelta(seconds=max(2, len(turns) * 2))
    parent_uuid = None
    lines = []
    for i,(prompt,response) in enumerate(turns):
        user_uuid,assistant_uuid = str(uuid.uuid4()), str(uuid.uuid4())
        lines.append(dict(type="user", uuid=user_uuid, parentUuid=parent_uuid, sessionId=session_id, timestamp=_iso(now + timedelta(seconds=i * 2)),
            cwd=str(project_root) if parent_uuid is None else None, message=dict(role="user", content=prompt)))
        lines.append(dict(type="assistant", uuid=assistant_uuid, parentUuid=user_uuid, sessionId=session_id,
            timestamp=_iso(now + timedelta(seconds=i * 2 + 1)), message=dict(role="assistant", content=[dict(type="text", text=strip_thinking(response))])))
        parent_uuid = assistant_uuid
    path.write_text("".join(json.dumps({k:v for k,v in line.items() if v is not None}, ensure_ascii=False, separators=(",", ":")) + "\n" for line in lines),
        encoding="utf-8")
    return dict(session_id=session_id, path=path)


class ClaudeBackend(BaseBackend):
    formatter_cls = AsyncStreamFormatter

    def __init__(self, shell=None, cwd=None, system_prompt="", plugin_dirs=None, cli_path=None):
        super().__init__(shell=shell, cwd=cwd, system_prompt=system_prompt, plugin_dirs=plugin_dirs, cli_path=cli_path)
        self._tool_server = None

    def _sdk_server(self):
        if self._tool_server is not None: return self._tool_server or None
        tools = self.tools.claude_sdk_tools(tool)
        self._tool_server = create_sdk_mcp_server(name="ipyai", tools=tools) if tools else False
        return self._tool_server or None

    def _options(self, *, model, think=None, resume=None, include_partial_messages=True, allow_tools=True):
        tools = BUILTIN_TOOLS if allow_tools else []
        custom = self.tools.claude_allowed_tool_names() if allow_tools else []
        server = self._sdk_server() if allow_tools else None
        allowed_tools = [*BUILTIN_TOOLS, *custom] if allow_tools else []
        plugins = [dict(type="local", path=o) for o in self.ctx.plugin_dirs]
        return ClaudeAgentOptions(model=model, cwd=self.ctx.cwd, cli_path=self.ctx.cli_path, system_prompt=self.ctx.system_prompt, tools=tools,
            allowed_tools=allowed_tools, include_partial_messages=include_partial_messages, continue_conversation=bool(resume), resume=resume,
            effort=effort_level(think), setting_sources=["user", "project"], mcp_servers={"ipy": server} if server else {},
            plugins=plugins)

    async def prepare_turn(self, *, prompt, model, think="l", provider_session_id=None, seed=None, tool_mode="on", ephemeral=False):
        seed = seed or ConversationSeed()
        state = {}
        session_id = provider_session_id
        if not session_id and seed.turns:
            info = write_synthetic_session(self.ctx.cwd, [(turn.full_prompt, replayable_assistant_text(turn.response)) for turn in seed.turns])
            session_id = info["session_id"]
            state["provider_session_id"] = session_id
        options = self._options(model=model, think=think, resume=session_id, include_partial_messages=True, allow_tools=tool_mode != "off")

        async def _stream():
            async with ClaudeSDKClient(options=options) as client:
                await client.query(prompt)
                thinking_open = False
                tools = {}
                async for message in client.receive_response():
                    if isinstance(message, StreamEvent):
                        event = message.event
                        if event.get("type") == "content_block_start" and event.get("content_block", {}).get("type") == "thinking":
                            if not thinking_open:
                                thinking_open = True
                                yield dict(kind="thinking_start")
                        elif event.get("type") == "content_block_delta":
                            delta = event.get("delta", {})
                            if delta.get("type") == "text_delta":
                                text = delta.get("text", "")
                                if text: yield text
                            elif delta.get("type") == "thinking_delta":
                                if not thinking_open:
                                    thinking_open = True
                                    yield dict(kind="thinking_start")
                                yield dict(kind="thinking_delta", delta=delta.get("thinking", ""))
                        elif event.get("type") == "content_block_stop" and thinking_open:
                            thinking_open = False
                            yield dict(kind="thinking_end")
                        continue

                    if isinstance(message, AssistantMessage):
                        if message.session_id: state["provider_session_id"] = message.session_id
                        for block in message.content:
                            if isinstance(block, ToolUseBlock):
                                tools[block.id] = dict(name=block.name, input=block.input)
                                yield dict(kind="tool_start", id=block.id, name=block.name, input=block.input)
                        continue

                    if isinstance(message, UserMessage):
                        blocks = message.content if isinstance(message.content, list) else []
                        for block in blocks:
                            if not isinstance(block, ToolResultBlock): continue
                            meta = tools.get(block.tool_use_id, {})
                            yield dict(kind="tool_complete", id=block.tool_use_id, name=meta.get("name"), input=meta.get("input"),
                                content=_stringify_content(block.content), is_error=bool(block.is_error))
                        continue

                    if isinstance(message, ResultMessage):
                        state["provider_session_id"] = message.session_id
                        continue

        return self.prepared_turn(_stream(), provider_session_id=session_id, state=state)


ClaudeSDKBackend = ClaudeBackend


class AsyncChat:
    def __init__(self, model, sp="", backend_factory=ClaudeBackend, **backend_kwargs):
        self.model,self.sp,self.backend_factory,self.backend_kwargs = model,sp,backend_factory,backend_kwargs

    async def __call__(self, prompt, think="l"):
        backend = self.backend_factory(system_prompt=self.sp, **self.backend_kwargs)
        return await backend.complete(prompt, model=self.model)
