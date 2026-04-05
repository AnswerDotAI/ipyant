import json, os, re, uuid
from collections.abc import Iterable
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

from claude_agent_sdk import AssistantMessage, ClaudeAgentOptions, ClaudeSDKClient, ResultMessage, StreamEvent, TextBlock
from claude_agent_sdk import ToolResultBlock, ToolUseBlock, UserMessage, create_sdk_mcp_server, tool
from claude_agent_sdk._internal.sessions import _get_project_dir


BUILTIN_TOOLS = ["Bash", "Edit", "Read", "Skill", "WebFetch", "WebSearch", "Write"]
_THINK_MAP = dict(l="low", m="medium", h="high")
_THINK_RE = re.compile(r"<thinking>\n.*?\n</thinking>\n*", flags=re.DOTALL)


def _blockquote(text): return "".join(f"> {line}\n" if line.strip() else ">\n" for line in text.splitlines()) if text else ""


def _effort(level): return _THINK_MAP.get(level, level or None)


def _iso(ts): return ts.replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _strip_thinking(text): return _THINK_RE.sub("", text or "").strip()


def _stringify_content(content):
    if content is None: return ""
    if isinstance(content, str): return content
    parts = []
    for item in content:
        if isinstance(item, dict) and item.get("type") == "text": parts.append(item.get("text", ""))
        else: parts.append(json.dumps(item, ensure_ascii=False, default=str))
    return "\n".join(o for o in parts if o)


def _compact_tool(name, args, result, is_error=False):
    call = f"{name}()" if not args else f"{name}({', '.join(f'{k}={v!r}' for k,v in sorted(args.items()))})"
    res = (result or "").strip().replace("\n", " ")
    if len(res) > 100: res = res[:97] + "..."
    status = " [error]" if is_error else ""
    return f"\n\n🔧 {call}{status} => {res}\n" if res else f"\n\n🔧 {call}{status}\n"


class AsyncStreamFormatter:
    def __init__(self):
        self.is_tty = False
        self.final_text = ""
        self.display_text = ""
        self._thinking_text = ""
        self._tool_text = ""

    def _update_display(self):
        parts = []
        if self._thinking_text: parts.append(_blockquote(self._thinking_text).rstrip())
        if self.final_text: parts.append(self.final_text.rstrip())
        if self._tool_text: parts.append(self._tool_text.rstrip())
        self.display_text = "\n\n".join(o for o in parts if o)

    def _append_final(self, text):
        if text: self.final_text += text
        self._update_display()

    def _format_event(self, event):
        if isinstance(event, str):
            self._append_final(event)
            return event
        if not isinstance(event, dict): return ""
        kind = event.get("kind")
        if kind == "thinking_start":
            self._thinking_text = ""
            self._update_display()
            return ""
        if kind == "thinking_delta":
            self._thinking_text += event.get("delta", "")
            self._update_display()
            return ""
        if kind == "thinking_end":
            stored = f"<thinking>\n{self._thinking_text}\n</thinking>\n\n" if self._thinking_text else ""
            self._thinking_text = ""
            self._append_final(stored)
            return "" if self.is_tty else stored
        if kind == "tool_start":
            name,args = event.get("name") or "tool", event.get("input") or {}
            self._tool_text = f"⌛ `{name}`{'' if not args else f' {json.dumps(args, ensure_ascii=False, default=str)}'}"
            self._update_display()
            return ""
        if kind == "tool_complete":
            self._tool_text = ""
            text = _compact_tool(event.get("name") or "tool", event.get("input") or {}, event.get("content") or "", event.get("is_error"))
            self._append_final(text)
            return "" if self.is_tty else text
        return ""

    async def format_stream(self, stream):
        async for o in stream: yield self._format_event(o)


class FullResponse(str):
    @property
    def content(self): return str(self)


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
            timestamp=_iso(now + timedelta(seconds=i * 2 + 1)), message=dict(role="assistant", content=[dict(type="text", text=_strip_thinking(response))])))
        parent_uuid = assistant_uuid
    path.write_text("".join(json.dumps({k:v for k,v in line.items() if v is not None}, ensure_ascii=False, separators=(",", ":")) + "\n" for line in lines),
        encoding="utf-8")
    return SimpleNamespace(session_id=session_id, path=path)


class ClaudeBackend:
    def __init__(self, shell=None, cwd=None, system_prompt="", plugin_dirs=None, cli_path=None):
        self.shell = shell
        self.cwd = str(Path(cwd or os.getcwd()).resolve())
        self.system_prompt = system_prompt
        self.plugin_dirs = [str(Path(o).resolve()) for o in (plugin_dirs or [])]
        self.cli_path = cli_path
        self._python_server = None

    def _sdk_server(self):
        if self._python_server is not None: return self._python_server
        ns = self.shell.user_ns

        async def _call_ns_tool(name, *args, **kwargs):
            fn = ns.get(name)
            if not callable(fn): raise NameError(f"{name!r} is not defined in the active IPython namespace")
            return await fn(*args, **kwargs)

        @tool("python", "Execute Python in the active IPython namespace", {"code": str})
        async def python_tool(args):
            code = args["code"]
            try:
                try: result = await _call_ns_tool("pyrun", code=code)
                except TypeError: result = await _call_ns_tool("pyrun", code)
                text = result if isinstance(result, str) else json.dumps(result, ensure_ascii=False, default=str)
                return dict(content=[dict(type="text", text=text)])
            except Exception as e: return dict(content=[dict(type="text", text=f"Error: {e}")], is_error=True)

        self._python_server = create_sdk_mcp_server(name="ipyant", tools=[python_tool])
        return self._python_server

    def _options(self, *, model, think=None, resume=None, include_partial_messages=True, allow_tools=True):
        tools = BUILTIN_TOOLS if allow_tools else []
        allowed_tools = [*BUILTIN_TOOLS, "mcp__ipy__python"] if allow_tools else []
        plugins = [dict(type="local", path=o) for o in self.plugin_dirs]
        return ClaudeAgentOptions(model=model, cwd=self.cwd, cli_path=self.cli_path, system_prompt=self.system_prompt, tools=tools,
            allowed_tools=allowed_tools, include_partial_messages=include_partial_messages, continue_conversation=bool(resume), resume=resume,
            effort=_effort(think), setting_sources=["user", "project"], mcp_servers={"ipy": self._sdk_server()} if allow_tools else {},
            plugins=plugins)

    async def complete(self, prompt, *, model):
        options = self._options(model=model, include_partial_messages=False, allow_tools=False)
        async with ClaudeSDKClient(options=options) as client:
            await client.query(prompt)
            parts = []
            async for message in client.receive_response():
                if isinstance(message, AssistantMessage):
                    parts += [block.text for block in message.content if isinstance(block, TextBlock)]
            return FullResponse("".join(parts).strip())

    async def stream_turn(self, prompt, *, model, think="l", resume=None, state=None):
        state = state if state is not None else {}
        options = self._options(model=model, think=think, resume=resume, include_partial_messages=True, allow_tools=True)
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
                    if message.session_id: state["session_id"] = message.session_id
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
                    state["session_id"] = message.session_id
                    continue


class AsyncChat:
    def __init__(self, model, sp="", backend_factory=ClaudeBackend, **backend_kwargs):
        self.model,self.sp,self.backend_factory,self.backend_kwargs = model,sp,backend_factory,backend_kwargs

    async def __call__(self, prompt, think="l"):
        backend = self.backend_factory(system_prompt=self.sp, **self.backend_kwargs)
        return await backend.complete(prompt, model=self.model)
