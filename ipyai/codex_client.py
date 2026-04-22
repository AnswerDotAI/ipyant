import asyncio, json, os, shlex
from collections import defaultdict
from importlib.metadata import version

from .backend_common import (BaseBackend, CommonStreamFormatter, ConversationSeed, compact_cmd, compact_tool, effort_level,
    seed_to_notebook_xml, tool_call, tool_name)

_HIST_SP = ("\n\nIf the current user input contains an <ipython-notebook> block, treat it as serialized prior notebook state. "
    "Respect all code, notes, and earlier prompt/response pairs contained inside it.")


def _json(obj): return json.dumps(obj, ensure_ascii=False, default=str)


def _pkg_version():
    try: return version("ipyai")
    except Exception: return "0"


def _codex_cmd():
    raw = os.environ.get("IPYAI_CODEX_CMD", "codex")
    return [*shlex.split(raw), "app-server", "--listen", "stdio://"]


def _content_items_text(items):
    if not items: return ""
    parts = []
    for o in items:
        if o.get("type") == "inputText": parts.append(o.get("text", ""))
        elif o.get("type") == "inputImage": parts.append(o.get("imageUrl", ""))
    return "\n".join(o for o in parts if o)


async def _call_tool(registry, name, args):
    if registry is None:
        return dict(success=False, contentItems=[dict(type="inputText", text=f"Error: tool {name!r} is not defined")])
    try: return dict(success=True, contentItems=[dict(type="inputText", text=await registry.call_text(name, args))])
    except Exception as e: return dict(success=False, contentItems=[dict(type="inputText", text=f"Error: {e}")])


AsyncStreamFormatter = CommonStreamFormatter
_tool_name,_tool_call,_compact_tool,_compact_cmd = tool_name,tool_call,compact_tool,compact_cmd


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

    async def start_thread(self, *, model=None, sp="", dynamic_tools=None, ephemeral=False, cwd=None):
        await self.ensure_initialized()
        params = dict(cwd=cwd or os.getcwd(), approvalPolicy="never", sandbox="workspace-write", ephemeral=ephemeral, personality="pragmatic")
        if model: params["model"] = model
        if sp: params["developerInstructions"] = sp + _HIST_SP
        if dynamic_tools: params["dynamicTools"] = dynamic_tools
        result = await self.request("thread/start", params)
        return result["thread"]["id"]

    async def resume_thread(self, thread_id, *, sp="", cwd=None):
        await self.ensure_initialized()
        params = dict(threadId=thread_id, cwd=cwd or os.getcwd(), approvalPolicy="never", sandbox="workspace-write", personality="pragmatic")
        if sp: params["developerInstructions"] = sp + _HIST_SP
        result = await self.request("thread/resume", params)
        return result["thread"]["id"]

    async def turn_stream(self, thread_id, prompt, *, tools=None, think=None, output_schema=None, cwd=None):
        async with self.turn_lock:
            params = dict(threadId=thread_id, input=[dict(type="text", text=prompt, text_elements=[])], cwd=cwd or os.getcwd(),
                approvalPolicy="never", personality="pragmatic", summary="detailed")
            if (effort := effort_level(think)): params["effort"] = effort
            if output_schema is not None: params["outputSchema"] = output_schema
            turn = await self.request("turn/start", params)
            turn_id = turn["turn"]["id"]
            consumer = self._consume_turn(thread_id, turn_id, tools)
            try:
                async for chunk in consumer: yield chunk
            except (asyncio.CancelledError, GeneratorExit):
                await consumer.aclose()
                try: await self.notify("turn/cancel", dict(threadId=thread_id, turnId=turn_id))
                except Exception: pass
                raise

    async def _consume_turn(self, thread_id, turn_id, tools):
        agent_seen,cmd_output,cmd_items = set(),defaultdict(str),{}
        saw_text = thinking = False
        while True:
            msg = await self.events.get()
            method = msg.get("method")
            params = msg.get("params") or {}
            if "id" in msg and method:
                if params.get("threadId") == thread_id and params.get("turnId") == turn_id:
                    await self.respond(msg["id"], await self._handle_request(method, params, tools))
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

    async def _handle_request(self, method, params, tools):
        if method == "item/tool/call": return await _call_tool(tools, params.get("tool"), params.get("arguments") or {})
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


class CodexBackend(BaseBackend):
    formatter_cls = AsyncStreamFormatter

    async def prepare_turn(self, *, prompt, model, think="l", provider_session_id=None, seed=None, tool_mode="on", ephemeral=False):
        seed = seed or ConversationSeed()
        client = get_codex_client()
        state = {}
        session_id = provider_session_id
        tools = self.tools if tool_mode != "off" else None
        if session_id:
            try:
                session_id = await client.resume_thread(session_id, sp=self.ctx.system_prompt, cwd=self.ctx.cwd)
                state["provider_session_id"] = session_id
            except Exception: pass
        if not session_id:
            dynamic_tools = await self.tools.codex_dynamic_tools() if tool_mode != "off" else None
            session_id = await client.start_thread(model=model, sp=self.ctx.system_prompt, dynamic_tools=dynamic_tools, ephemeral=ephemeral, cwd=self.ctx.cwd)
            if seed.startup_events:
                seed_prompt = seed_to_notebook_xml(seed) + "The XML above describes a notebook already loaded into the live IPython session. "
                seed_prompt += "Treat it as prior session context for this thread. Reply with ok and nothing else."
                async for _ in client.turn_stream(session_id, seed_prompt, tools=tools, think=think, cwd=self.ctx.cwd): pass
            state["provider_session_id"] = session_id

        stream = client.turn_stream(session_id, prompt, tools=tools, think=think, cwd=self.ctx.cwd)
        return self.prepared_turn(stream, provider_session_id=session_id, state=state)
