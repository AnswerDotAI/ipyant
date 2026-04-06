import asyncio, ast, html, json, os, re, shlex
from collections import defaultdict
from importlib.metadata import version

from .tooling import call_ns_tool, openai_tool_schemas

_HIST_SP = ("\n\nIf the current user input contains an <ipython-notebook> block, treat it as serialized prior notebook state. "
    "Respect all code, notes, and earlier prompt/response pairs contained inside it.")
_TOOL_PREFIX_RE = re.compile(r"^mcp__\w+__")


def _blockquote(text): return "".join(f"> {line}\n" if line.strip() else ">\n" for line in text.splitlines()) if text else ""


def _json(obj): return json.dumps(obj, ensure_ascii=False, default=str)


def _xml_text(text): return html.escape(text or "", quote=False)


def _pkg_version():
    try: return version("ipyai")
    except Exception: return "0"


def _codex_cmd():
    raw = os.environ.get("IPYAI_CODEX_CMD", "codex")
    return [*shlex.split(raw), "app-server", "--listen", "stdio://"]


def _fenced_block(text, info=""):
    text = text or ""
    fence = "~" * 3
    while fence in text: fence += "~"
    if text and not text.endswith("\n"): text += "\n"
    return f"{fence}{info}\n{text}{fence}\n"


def _dynamic_tools(tools):
    res = []
    for o in tools or []:
        fn = dict(o.get("function") or {})
        if not fn.get("name"): continue
        res.append(dict(name=fn["name"], description=fn.get("description") or "", inputSchema=fn.get("parameters") or dict(type="object")))
    return res or None


def _effort_level(level): return dict(l="low", m="medium", h="high").get(level, level or None)


def _tool_name(name): return _TOOL_PREFIX_RE.sub("", name or "")


def _tool_call(name, args):
    name = _tool_name(name)
    return f"{name}()" if not args else f"{name}({', '.join(f'{k}={v!r}' for k,v in sorted(args.items()))})"


def _compact_tool(name, args, result):
    call = _tool_call(name, args)
    res = (result or "").strip().replace("\n", " ")
    if len(res) > 80: res = res[:77] + "..."
    return f"\n\n🔧 {call} => {res}\n\n" if res else f"\n\n🔧 {call}\n\n"


def _compact_cmd(command, output, exit_code):
    res = (output or "").strip().replace("\n", " ")
    if len(res) > 80: res = res[:77] + "..."
    status = "" if exit_code in (None, 0) else f" [exit {exit_code}]"
    return f"\n\n🔧 {command}{status} => {res}\n\n" if res else f"\n\n🔧 {command}{status}\n\n"


def _content_items_text(items):
    if not items: return ""
    parts = []
    for o in items:
        if o.get("type") == "inputText": parts.append(o.get("text", ""))
        elif o.get("type") == "inputImage": parts.append(o.get("imageUrl", ""))
    return "\n".join(o for o in parts if o)


def _is_note(source):
    try: tree = ast.parse(source)
    except SyntaxError: return False
    return (len(tree.body) == 1 and isinstance(tree.body[0], ast.Expr) and isinstance(tree.body[0].value, ast.Constant)
        and isinstance(tree.body[0].value.value, str))


def _notebook_xml(events):
    parts = ["<ipython-notebook>"]
    for o in events or []:
        if o.get("kind") == "code":
            tag = "note" if _is_note(o.get("source", "")) else "code"
            parts.append(f'<{tag} line="{int(o.get("line", 0))}">{_xml_text(o.get("source", ""))}</{tag}>')
        elif o.get("kind") == "prompt":
            parts.append(f'<turn line="{int(o.get("history_line", 0))}"><user>{_xml_text(o.get("full_prompt", ""))}</user>'
                f'<assistant>{_xml_text(o.get("response", ""))}</assistant></turn>')
    parts.append("</ipython-notebook>")
    return "".join(parts)


async def _call_tool(ns, name, args):
    fn = ns.get(name)
    if not callable(fn): return dict(success=False, contentItems=[dict(type="inputText", text=f"Error: tool {name!r} is not defined")])
    try: return dict(success=True, contentItems=[dict(type="inputText", text=await call_ns_tool(ns, name, args))])
    except Exception as e: return dict(success=False, contentItems=[dict(type="inputText", text=f"Error: {e}")])


class AsyncStreamFormatter:
    def __init__(self):
        self.is_tty = False
        self.final_text = ""
        self.display_text = ""
        self._live_commands = {}
        self._tool_text = ""
        self._thinking_text = ""

    def _update_display(self):
        parts = []
        if self._thinking_text: parts.append(_blockquote(self._thinking_text))
        if self.final_text: parts.append(self.final_text)
        if self._tool_text: parts.append(self._tool_text)
        live = "\n\n".join(self._live_command_text(o) for o in self._live_commands.values())
        if live: parts.append(live)
        self.display_text = "\n\n".join(o.rstrip() for o in parts if o).rstrip()

    def _append_final(self, text):
        if text: self.final_text += text
        self._update_display()

    def _live_command_text(self, state):
        cmd = html.escape(state.get("command") or "command")
        text = f"⌛ <code>{cmd}</code>"
        if state.get("output"): text += "\n\n" + _fenced_block(state["output"], "text")
        return text.rstrip()

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
            self._tool_text = f"⌛ `{_tool_call(event.get('name') or 'tool', event.get('input') or {})}`"
            self._update_display()
            return ""
        if kind == "tool_complete":
            self._tool_text = ""
            text = _compact_tool(event.get("name") or "tool", event.get("input") or {}, event.get("content") or "")
            self._append_final(text)
            return "" if self.is_tty else text
        if kind == "command_start":
            self._live_commands[event.get("id")] = dict(command=event.get("command"), cwd=event.get("cwd"), output="")
            self._update_display()
            return ""
        if kind == "command_delta":
            state = self._live_commands.setdefault(event.get("id"), dict(command=event.get("command"), cwd=event.get("cwd"), output=""))
            if event.get("command") and not state.get("command"): state["command"] = event["command"]
            state["output"] += event.get("delta", "")
            self._update_display()
            return ""
        if kind == "command_complete":
            self._live_commands.pop(event.get("id"), None)
            text = event.get("text", "")
            self._append_final(text)
            return "" if self.is_tty else text
        text = event.get("text", "")
        if text: self._append_final(text)
        return text

    async def format_stream(self, stream):
        async for o in stream: yield self._format_event(o)


class FullResponse(str):
    @property
    def content(self): return str(self)


class _CodexAppServer:
    def __init__(self):
        self.proc = None
        self.pending = {}
        self.events = None
        self.read_task = self.err_task = None
        self.req_id = 0
        self.init_lock = asyncio.Lock()
        self.turn_lock = asyncio.Lock()
        self.initialized = False

    async def _start(self):
        if self.proc and self.proc.returncode is None: return
        self.proc = await asyncio.create_subprocess_exec(*_codex_cmd(), stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE, start_new_session=True)
        self.pending = {}
        self.events = asyncio.Queue()
        self.read_task = asyncio.create_task(self._read_stdout())
        self.err_task = asyncio.create_task(self._drain_stderr())
        self.initialized = False

    async def _drain_stderr(self):
        while self.proc and self.proc.stderr:
            if not await self.proc.stderr.readline(): break

    async def _read_stdout(self):
        try:
            while self.proc and self.proc.stdout:
                raw = await self.proc.stdout.readline()
                if not raw: break
                line = raw.decode("utf-8", errors="replace").strip()
                if not line: continue
                try: msg = json.loads(line)
                except Exception: continue
                if "id" in msg and ("result" in msg or "error" in msg) and "method" not in msg:
                    fut = self.pending.pop(msg["id"], None)
                    if fut and not fut.done(): fut.set_result(msg)
                else: await self.events.put(msg)
        finally:
            err = RuntimeError("codex app-server exited")
            for fut in self.pending.values():
                if not fut.done(): fut.set_exception(err)
            self.pending.clear()

    async def _send(self, msg):
        await self._start()
        self.proc.stdin.write((_json(msg) + "\n").encode())
        await self.proc.stdin.drain()

    async def request(self, method, params):
        self.req_id += 1
        rid = str(self.req_id)
        fut = asyncio.get_running_loop().create_future()
        self.pending[rid] = fut
        await self._send(dict(id=rid, method=method, params=params))
        msg = await fut
        if "error" in msg: raise RuntimeError(msg["error"])
        return msg.get("result")

    async def respond(self, rid, result): await self._send(dict(id=rid, result=result))

    async def notify(self, method, params=None):
        msg = dict(method=method)
        if params is not None: msg["params"] = params
        await self._send(msg)

    async def ensure_initialized(self):
        async with self.init_lock:
            if self.initialized and self.proc and self.proc.returncode is None: return
            self.initialized = False
            await self._start()
            await self.request("initialize", dict(clientInfo=dict(name="ipyai", title="ipyai", version=_pkg_version()),
                capabilities=dict(experimentalApi=True)))
            await self.notify("initialized")
            self.initialized = True

    async def start_thread(self, *, model=None, sp="", tools=None, ephemeral=False):
        await self.ensure_initialized()
        params = dict(cwd=os.getcwd(), approvalPolicy="never", sandbox="workspace-write", ephemeral=ephemeral, personality="pragmatic")
        if model: params["model"] = model
        if sp: params["developerInstructions"] = sp + _HIST_SP
        if (dtools := _dynamic_tools(tools)): params["dynamicTools"] = dtools
        result = await self.request("thread/start", params)
        return result["thread"]["id"]

    async def resume_thread(self, thread_id, *, sp=""):
        await self.ensure_initialized()
        params = dict(threadId=thread_id, cwd=os.getcwd(), approvalPolicy="never", sandbox="workspace-write", personality="pragmatic")
        if sp: params["developerInstructions"] = sp + _HIST_SP
        result = await self.request("thread/resume", params)
        return result["thread"]["id"]

    async def turn_stream(self, thread_id, prompt, *, ns=None, think=None, output_schema=None):
        async with self.turn_lock:
            params = dict(threadId=thread_id, input=[dict(type="text", text=prompt, text_elements=[])], cwd=os.getcwd(),
                approvalPolicy="never", personality="pragmatic", summary="detailed")
            if (effort := _effort_level(think)): params["effort"] = effort
            if output_schema is not None: params["outputSchema"] = output_schema
            turn = await self.request("turn/start", params)
            turn_id = turn["turn"]["id"]
            consumer = self._consume_turn(thread_id, turn_id, ns or {})
            try:
                async for chunk in consumer: yield chunk
            except (asyncio.CancelledError, GeneratorExit):
                await consumer.aclose()
                try: await self.notify("turn/cancel", dict(threadId=thread_id, turnId=turn_id))
                except Exception: pass
                raise

    async def _consume_turn(self, thread_id, turn_id, ns):
        agent_seen,cmd_output,cmd_items = set(),defaultdict(str),{}
        saw_text = thinking = False
        while True:
            msg = await self.events.get()
            method = msg.get("method")
            params = msg.get("params") or {}
            if "id" in msg and method:
                if params.get("threadId") == thread_id and params.get("turnId") == turn_id:
                    await self.respond(msg["id"], await self._handle_request(method, params, ns))
                continue
            if params.get("threadId") not in (None, thread_id): continue
            if params.get("turnId") not in (None, turn_id): continue
            if method == "error": raise RuntimeError(params)
            if method == "item/started" and (item := params.get("item")):
                if item.get("type") == "reasoning" and not thinking:
                    thinking = True
                    yield dict(kind="thinking_start")
                elif item.get("type") == "dynamicToolCall":
                    yield dict(kind="tool_start", name=item.get("tool"), input=item.get("arguments") or {})
                elif item.get("type") == "commandExecution":
                    cmd_items[item.get("id")] = dict(command=item.get("command"), cwd=item.get("cwd"))
                    yield dict(kind="command_start", id=item.get("id"), command=item.get("command"), cwd=item.get("cwd"))
                elif item.get("type") == "agentMessage" and saw_text and item.get("phase") == "final_answer": yield "\n\n"
                continue
            if method in ("item/reasoning/textDelta", "item/reasoning/summaryTextDelta"):
                yield dict(kind="thinking_delta", delta=params.get("delta", ""))
                continue
            if method == "item/agentMessage/delta":
                if thinking:
                    yield dict(kind="thinking_end")
                    thinking = False
                saw_text = True
                agent_seen.add(params.get("itemId"))
                yield params.get("delta", "")
                continue
            if method == "item/commandExecution/outputDelta":
                item_id = params.get("itemId")
                cmd_output[item_id] += params.get("delta", "")
                item = cmd_items.get(item_id) or {}
                yield dict(kind="command_delta", id=item_id, delta=params.get("delta", ""), command=item.get("command"), cwd=item.get("cwd"))
                continue
            if method == "item/completed" and (item := params.get("item")):
                if item.get("type") == "reasoning" and thinking:
                    yield dict(kind="thinking_end")
                    thinking = False
                    continue
                if item.get("type") == "dynamicToolCall":
                    saw_text = True
                    yield dict(kind="tool_complete", name=item.get("tool"), input=item.get("arguments") or {},
                        content=_content_items_text(item.get("contentItems")))
                    continue
                if (text := self._completed_item_text(item, agent_seen, cmd_output)):
                    if item.get("type") != "agentMessage" and saw_text and not text.startswith("\n"): text = "\n" + text
                    if item.get("type") == "commandExecution":
                        cmd_items.pop(item.get("id"), None)
                        saw_text = True
                        yield dict(kind="command_complete", id=item.get("id"), text=text)
                    else:
                        saw_text = True
                        yield text
                continue
            if method == "turn/completed":
                turn = params.get("turn") or {}
                if turn.get("error"): raise RuntimeError(turn["error"])
                break

    async def _handle_request(self, method, params, ns):
        if method == "item/tool/call": return await _call_tool(ns, params.get("tool"), params.get("arguments") or {})
        if method == "item/commandExecution/requestApproval": return dict(decision="accept")
        if method == "item/fileChange/requestApproval": return dict(decision="accept")
        if method == "item/permissions/requestApproval": return dict(permissions={}, scope="turn")
        if method == "item/tool/requestUserInput": return dict(answers={})
        if method == "mcpServer/elicitation/request": return dict(action="decline")
        return {}

    def _completed_item_text(self, item, agent_seen, cmd_output):
        typ = item.get("type")
        if typ == "agentMessage":
            if item.get("id") in agent_seen: return ""
            return item.get("text", "")
        if typ == "dynamicToolCall":
            return _compact_tool(item.get("tool", "tool"), item.get("arguments") or {}, _content_items_text(item.get("contentItems")))
        if typ == "commandExecution":
            output = item.get("aggregatedOutput")
            if output is None: output = cmd_output.get(item.get("id"), "")
            return _compact_cmd(item.get("command") or "", output, item.get("exitCode"))
        return ""


_client = None


def get_codex_client():
    global _client
    if _client is None: _client = _CodexAppServer()
    return _client


class CodexBackend:
    formatter_cls = AsyncStreamFormatter

    def __init__(self, shell=None, cwd=None, system_prompt="", plugin_dirs=None, cli_path=None):
        self.shell = shell
        self.cwd = cwd
        self.system_prompt = system_prompt

    @property
    def ns(self): return getattr(self.shell, "user_ns", {})

    def _tools(self): return openai_tool_schemas(self.ns)

    async def complete(self, prompt, *, model):
        client = get_codex_client()
        thread_id = await client.start_thread(model=model, sp=self.system_prompt, tools=self._tools(), ephemeral=True)
        text = ""
        async for chunk in client.turn_stream(thread_id, prompt, think="l"):
            if isinstance(chunk, str): text += chunk
        return FullResponse(text.strip())

    async def bootstrap_session(self, *, model, think="l", session_id=None, records=None, events=None, state=None):
        client = get_codex_client()
        if session_id:
            try:
                session_id = await client.resume_thread(session_id, sp=self.system_prompt)
                if state is not None: state["session_id"] = session_id
                return session_id
            except Exception: pass
        thread_id = await client.start_thread(model=model, sp=self.system_prompt, tools=self._tools(), ephemeral=True)
        if events:
            prompt = _notebook_xml(events) + "The XML above describes a notebook already loaded into the live IPython session. Treat it as prior "
            prompt += "session context for this thread. Reply with ok and nothing else."
            async for _ in client.turn_stream(thread_id, prompt, ns=self.ns, think=think): pass
        if state is not None: state["session_id"] = thread_id
        return thread_id

    async def stream_turn(self, prompt, *, model, think="l", session_id=None, records=None, events=None, state=None):
        async for chunk in get_codex_client().turn_stream(session_id, prompt, ns=self.ns, think=think): yield chunk
