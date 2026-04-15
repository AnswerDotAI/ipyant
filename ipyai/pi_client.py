import asyncio, json, os, shlex, tempfile
from pathlib import Path

from .backend_common import BaseBackend, CommonStreamFormatter, ConversationSeed, effort_level as _effort, seed_to_notebook_xml
from .tooling import call_ns_tool


def _json(obj): return json.dumps(obj, ensure_ascii=False, default=str)


async def _read_json_lines(reader):
    """Yield parsed JSON dicts from an async line-delimited stream."""
    while True:
        raw = await reader.readline()
        if not raw:
            return
        line = raw.decode("utf-8", errors="replace").rstrip("\n\r")
        if not line:
            continue
        try:
            yield json.loads(line)
        except Exception:
            continue



def _pi_cmd(model, *, session=None, ephemeral=False, system_prompt="", extension=None, tool_mode="on"):
    raw = os.environ.get("IPYAI_PI_CMD", "pi")
    cmd = [*shlex.split(raw), "--mode", "rpc"]
    if model: cmd += ["--model", model]
    if system_prompt: cmd += ["--system-prompt", system_prompt]
    if ephemeral: cmd += ["--no-session"]
    elif session: cmd += ["--session", session]
    # ipyai controls tool exposure via the Python bridge; keep pi built-ins disabled for parity across backends.
    cmd += ["--no-tools"]
    if extension:
        cmd += ["--no-extensions", "--no-skills", "--no-prompt-templates", "--no-themes", "-e", extension]
    return cmd


def _content_text(content):
    if isinstance(content, str): return content
    if not isinstance(content, list): return ""
    parts = []
    for o in content:
        if not isinstance(o, dict): continue
        if o.get("type") == "text": parts.append(o.get("text", ""))
    return "".join(parts)


def _partial_text(partial):
    if not isinstance(partial, dict): return ""
    return _content_text(partial.get("content"))


def _is_shell_tool(name): return name == "bash"


def _seed_prompt(seed):
    text = seed_to_notebook_xml(seed)
    return text + "The XML above describes a notebook already loaded into the live IPython session. Treat it as prior session context for this thread. Reply with ok and nothing else."


class _PiRpcProcess:
    def __init__(self, cmd, env=None, cwd=None):
        self.cmd,self.env,self.cwd = cmd,env,cwd
        self.proc = None
        self.pending = {}
        self.events = asyncio.Queue()
        self.read_task = self.err_task = None
        self.req_id = 0

    async def start(self):
        if self.proc and self.proc.returncode is None: return
        self.proc = await asyncio.create_subprocess_exec(*self.cmd, stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE, cwd=self.cwd, env=self.env, start_new_session=True)
        self.pending = {}
        self.events = asyncio.Queue()
        self.read_task = asyncio.create_task(self._read_stdout())
        self.err_task = asyncio.create_task(self._drain_stderr())

    async def _drain_stderr(self):
        while self.proc and self.proc.stderr:
            if not await self.proc.stderr.readline(): break

    async def _read_stdout(self):
        try:
            async for msg in _read_json_lines(self.proc.stdout):
                if msg.get("type") == "response" and msg.get("id") in self.pending:
                    fut = self.pending.pop(msg["id"], None)
                    if fut and not fut.done(): fut.set_result(msg)
                else: await self.events.put(msg)
        finally:
            err = RuntimeError("pi rpc process exited")
            for fut in self.pending.values():
                if not fut.done(): fut.set_exception(err)
            self.pending.clear()
            await self.events.put(None)

    async def _send(self, msg):
        await self.start()
        self.proc.stdin.write((_json(msg) + "\n").encode())
        await self.proc.stdin.drain()

    async def request(self, typ, **kwargs):
        self.req_id += 1
        rid = str(self.req_id)
        fut = asyncio.get_running_loop().create_future()
        self.pending[rid] = fut
        await self._send(dict(id=rid, type=typ, **kwargs))
        msg = await fut
        if not msg.get("success", False): raise RuntimeError(msg.get("error") or f"pi rpc {typ} failed")
        return msg

    async def abort(self):
        try: await self.request("abort")
        except Exception: pass

    async def close(self):
        if self.proc and self.proc.returncode is None:
            try:
                self.proc.terminate()
                await asyncio.wait_for(self.proc.wait(), timeout=2)
            except Exception:
                self.proc.kill()
        for t in (self.read_task, self.err_task):
            if t and not t.done(): t.cancel()


class PiToolBridge:
    def __init__(self, tools):
        self.tools = tools
        self.server = None
        self.writer = None
        self.tasks = set()
        self.tmpdir = None
        self.socket_path = None

    @property
    def env(self): return {} if not self.socket_path else {"IPYAI_PI_TOOL_SOCKET": self.socket_path}

    def payload(self):
        tools = []
        for o in self.tools.openai_schemas():
            fn = o.get("function") or {}
            tools.append(dict(name=fn.get("name") or "", description=fn.get("description") or "", parameters=fn.get("parameters") or dict(type="object")))
        return dict(type="register_tools", tools=[o for o in tools if o["name"]])

    async def start(self):
        if self.server is not None: return
        self.tmpdir = tempfile.TemporaryDirectory(prefix="ipyai-pi-")
        self.socket_path = str(Path(self.tmpdir.name) / "tool-bridge.sock")
        self.server = await asyncio.start_unix_server(self._handle_client, path=self.socket_path)

    async def _handle_client(self, reader, writer):
        self.writer = writer
        writer.write((_json(self.payload()) + "\n").encode())
        await writer.drain()
        try:
            async for msg in _read_json_lines(reader):
                task = asyncio.create_task(self._handle_message(msg, writer))
                self.tasks.add(task)
                task.add_done_callback(self.tasks.discard)
        finally:
            if self.writer is writer: self.writer = None
            writer.close()
            await writer.wait_closed()

    async def _handle_message(self, msg, writer):
        if msg.get("type") != "tool_call": return
        rid,name,args = msg.get("id"),msg.get("name"),msg.get("args") or {}
        try:
            text = await call_ns_tool(self.tools.ns, name, args)
            result = dict(type="tool_result", id=rid, isError=False, content=[dict(type="text", text=text)])
        except Exception as e:
            result = dict(type="tool_result", id=rid, isError=True, content=[dict(type="text", text=f"Error: {e}")])
        writer.write((_json(result) + "\n").encode())
        await writer.drain()

    async def close(self):
        for t in list(self.tasks):
            if not t.done(): t.cancel()
        if self.writer:
            self.writer.close()
            await self.writer.wait_closed()
            self.writer = None
        if self.server:
            self.server.close()
            await self.server.wait_closed()
            self.server = None
        if self.tmpdir:
            self.tmpdir.cleanup()
            self.tmpdir = None
            self.socket_path = None


class PiBackend(BaseBackend):
    formatter_cls = CommonStreamFormatter

    async def _stream_prompt(self, proc, prompt):
        await proc.request("prompt", message=prompt)
        tool_meta,last_partial = {},{}
        while True:
            msg = await proc.events.get()
            if msg is None: break
            typ = msg.get("type")
            if typ == "agent_end": break
            if typ == "message_update":
                event = msg.get("assistantMessageEvent") or {}
                etyp = event.get("type")
                if etyp == "text_delta":
                    if (delta := event.get("delta", "")): yield delta
                elif etyp == "thinking_start": yield dict(kind="thinking_start")
                elif etyp == "thinking_delta": yield dict(kind="thinking_delta", delta=event.get("delta", ""))
                elif etyp == "thinking_end": yield dict(kind="thinking_end")
                continue
            if typ == "tool_execution_start":
                tool_id,name,args = msg["toolCallId"],msg["toolName"],msg["args"]
                tool_meta[tool_id] = dict(name=name, args=args)
                last_partial[tool_id] = ""
                if _is_shell_tool(name):
                    yield dict(kind="command_start", id=tool_id, command=args.get("command"), cwd=self.ctx.cwd)
                else: yield dict(kind="tool_start", id=tool_id, name=name, input=args)
                continue
            if typ == "tool_execution_update":
                tool_id,name,args = msg["toolCallId"],msg["toolName"],msg["args"]
                if not _is_shell_tool(name): continue
                text = _partial_text(msg["partialResult"])
                prev = last_partial.get(tool_id, "")
                delta = text[len(prev):] if text.startswith(prev) else text
                last_partial[tool_id] = text
                if delta: yield dict(kind="command_delta", id=tool_id, delta=delta, command=args.get("command"), cwd=self.ctx.cwd)
                continue
            if typ == "tool_execution_end":
                tool_id,name = msg["toolCallId"],msg["toolName"]
                meta,args = tool_meta[tool_id],tool_meta[tool_id]["args"]
                result = msg["result"]
                content = _content_text(result["content"])
                if _is_shell_tool(name):
                    yield dict(kind="command_complete", id=tool_id, command=args.get("command"),
                        output=content or last_partial.get(tool_id, ""), exit_code=result["details"].get("exitCode"))
                else:
                    yield dict(kind="tool_complete", id=tool_id, name=meta["name"], input=args, content=content,
                        is_error=msg["isError"])
                continue

    async def _run_attempt(self, *, prompt, model, think, seed, tool_mode, ephemeral, session_path, state):
        bridge = None
        if tool_mode != "off" and self.tools.names():
            bridge = PiToolBridge(self.tools)
            await bridge.start()

        extension = str(Path(__file__).resolve().parent / "extensions" / "ipyai-bridge.ts") if bridge else None
        env = os.environ.copy()
        if bridge: env.update(bridge.env)
        cmd = _pi_cmd(model, session=session_path, ephemeral=ephemeral, system_prompt=self.ctx.system_prompt, extension=extension, tool_mode=tool_mode)
        proc = _PiRpcProcess(cmd, env=env, cwd=self.ctx.cwd)
        aborted = False
        try:
            await proc.start()
            await proc.request("set_thinking_level", level=_effort(think))
            if not session_path and seed.startup_events:
                async for _ in self._stream_prompt(proc, _seed_prompt(seed)): pass
            async for o in self._stream_prompt(proc, prompt): yield o
            data = (await proc.request("get_state")).get("data") or {}
            if (session_file := data.get("sessionFile")): state["provider_session_id"] = session_file
        except (asyncio.CancelledError, GeneratorExit):
            aborted = True
            await proc.abort()
            raise
        finally:
            if not aborted: await proc.abort()
            await proc.close()
            if bridge: await bridge.close()

    async def prepare_turn(self, *, prompt, model, think="l", provider_session_id=None, seed=None, tool_mode="on", ephemeral=False):
        seed = seed or ConversationSeed()
        state = {}

        async def _stream():
            attempts = [provider_session_id] if provider_session_id or ephemeral else [None]
            if provider_session_id and not ephemeral: attempts.append(None)
            last = None
            for i,session_path in enumerate(attempts):
                try:
                    async for o in self._run_attempt(prompt=prompt, model=model, think=think, seed=seed, tool_mode=tool_mode, ephemeral=ephemeral,
                        session_path=session_path, state=state):
                        yield o
                    return
                except Exception as e:
                    last = e
                    if i == len(attempts)-1: raise
            if last: raise last

        return self.prepared_turn(_stream(), provider_session_id=provider_session_id, state=state)
