"IPyAIShell — ZMQTerminalInteractiveShell subclass. jupyter_console's shell does NOT inherit from InteractiveShell, so we synthesise the subset of the InteractiveShell API our extension needs (user_ns, input_transformer_manager, magics, display_pub, showtraceback) plus kittytgp image rendering, Rich markdown rendering, client-side iopub output buffer, prompt-mode prompt swap, and async run_cell / interact overrides that route ipyai magics through awaiting on the existing event loop."
import base64, inspect, sys, traceback
from collections import defaultdict

from IPython.core.inputtransformer2 import TransformerManager
from jupyter_console.ptshell import ZMQTerminalInteractiveShell, ask_yes_no
from prompt_toolkit.history import History
from traitlets import Any as TAny, Enum, default, observe


_CODE_SQL = ("SELECT source_raw AS text, session, line AS ord FROM history "
    "WHERE source_raw IS NOT NULL AND source_raw != '' ORDER BY session DESC, ord DESC LIMIT ?")
_PROMPT_SQL = ("SELECT prompt AS text, session, history_line AS ord FROM claude_prompts "
    "WHERE prompt IS NOT NULL AND prompt != '' ORDER BY session DESC, ord DESC LIMIT ?")
_BOTH_SQL = (
    "SELECT text FROM ("
    " SELECT source_raw AS text, session, line AS ord, 0 AS kind FROM history WHERE source_raw IS NOT NULL AND source_raw != ''"
    " UNION ALL"
    " SELECT prompt AS text, session, history_line AS ord, 1 AS kind FROM claude_prompts WHERE prompt IS NOT NULL AND prompt != ''"
    ") ORDER BY session DESC, ord DESC, kind DESC LIMIT ?")


class IPyAIHistory(History):
    "prompt_toolkit History backed by the shared sqlite. mode_fn returns 'prompt' (claude_prompts only), 'code' (history only), or None (both interleaved)."
    def __init__(self, db, session_number, mode_fn=None, load_n=1000):
        super().__init__()
        self.db, self.session_number, self.load_n = db, session_number, load_n
        self.mode_fn = mode_fn or (lambda: None)
        self._refresh()

    def append_string(self, string):
        self._loaded = False
        self._refresh()

    def _refresh(self):
        if not self._loaded: self._loaded_strings = list(self.load_history_strings())

    def load_history_strings(self):
        mode = self.mode_fn()
        sql = _PROMPT_SQL if mode == "prompt" else _CODE_SQL if mode == "code" else _BOTH_SQL
        last = ""
        for row in self.db.execute(sql, (self.load_n,)):
            cell = (row[0] or "").rstrip()
            if cell and cell != last:
                yield cell
                last = cell

    def store_string(self, string): pass


MAX_BUFFER_CHARS = 200_000
_IPYAI_PREFIXES = ("get_ipython().run_cell_magic('ipyai'", 'get_ipython().run_cell_magic("ipyai"', "get_ipython().run_line_magic('ipyai'",
    'get_ipython().run_line_magic("ipyai"', "%ipyai", "%%ipyai")


class _ClientDisplayPub:
    "Minimal stand-in for InteractiveShell.display_pub exposing _is_publishing (used by _suppress_output_history)."
    def __init__(self): self._is_publishing = False


class IPyAIShell(ZMQTerminalInteractiveShell):
    _instance = None  # shadow the base SingletonConfigurable slot so our .instance() doesn't return the base's

    image_handler = Enum(("PIL", "stream", "tempfile", "callable", "kittytgp"), default_value="kittytgp", allow_none=True,
        config=True, help="Image dispatch mode; selects handle_image_<value>.")

    output_buffer = TAny()
    _ipyai_bridge = TAny(default_value=None, allow_none=True)
    _ipyai_extension = TAny(default_value=None, allow_none=True)
    user_ns = TAny()
    input_transformer_manager = TAny()
    display_pub = TAny()

    @default("output_buffer")
    def _default_output_buffer(self): return defaultdict(str)

    @default("user_ns")
    def _default_user_ns(self): return {}

    @default("input_transformer_manager")
    def _default_itm(self): return TransformerManager()

    @default("display_pub")
    def _default_display_pub(self): return _ClientDisplayPub()

    @observe("client")
    def _client_changed(self, change):
        "Modern @observe-style handler; decorating with @observe shadows and silences the parent's deprecated magic-name handler."
        new = change["new"]
        if new is None: return
        self.session_id = new.session.session

    def register_magics(self, magics):
        "No-op. Our run_cell override intercepts ipyai magics directly; no magic-dispatch machinery on the client."

    def handle_rich_data(self, data):
        if "text/markdown" in data:
            self._render_markdown(data["text/markdown"])
            return True
        return super().handle_rich_data(data)

    def _render_markdown(self, text):
        from rich.console import Console
        from rich.markdown import Markdown
        Console(file=sys.stdout, force_terminal=sys.stdout.isatty(), highlight=False, soft_wrap=True).print(Markdown(text))

    def handle_image_kittytgp(self, data, mime):
        if mime != "image/png": return False
        try: from kittytgp import build_render_bytes
        except ImportError: return False
        raw = base64.decodebytes(data[mime].encode("ascii"))
        class _T:
            def fileno(self): return sys.stdout.fileno()
        try: payload = build_render_bytes(raw, out=_T())
        except Exception: return False
        sys.stdout.write(payload.decode("utf-8"))
        sys.stdout.flush()
        return True

    def _append_output(self, exec_count, text):
        if not text or exec_count is None: return
        buf = self.output_buffer[exec_count]
        if len(buf) + len(text) > MAX_BUFFER_CHARS: return
        self.output_buffer[exec_count] = buf + text

    def install_iopub_tee(self):
        "Wrap client.iopub_channel.get_msg so every iopub message also populates output_buffer."
        chan = self.client.iopub_channel
        if getattr(chan, "_ipyai_teed", False): return
        orig = chan.get_msg
        def _tee(*a, **kw):
            msg = orig(*a, **kw)
            try: self._capture_output(msg)
            except Exception: pass
            return msg
        chan.get_msg = _tee
        chan._ipyai_teed = True

    def _capture_output(self, sub_msg):
        typ = sub_msg.get("msg_type")
        content = sub_msg.get("content") or {}
        parent = sub_msg.get("parent_header") or {}
        ec = parent.get("execution_count") or content.get("execution_count")
        if typ == "stream": self._append_output(ec, content.get("text", ""))
        elif typ == "execute_result":
            data = content.get("data") or {}
            if "text/markdown" in data: self._append_output(ec, data["text/markdown"])
            elif "text/plain" in data: self._append_output(ec, data["text/plain"])
        elif typ == "display_data":
            data = content.get("data") or {}
            if "text/markdown" in data: self._append_output(ec, data["text/markdown"])
            elif "text/plain" in data: self._append_output(ec, data["text/plain"])
            elif "image/png" in data: self._append_output(ec, "[image/png]")
        elif typ == "error":
            tb = "\n".join(content.get("traceback") or [])
            if tb: self._append_output(ec, tb)

    def _is_ipyai_magic(self, code):
        s = code.lstrip()
        return any(s.startswith(p) for p in _IPYAI_PREFIXES)

    async def arun_cell(self, cell, store_history=True):
        transformed = self.input_transformer_manager.transform_cell(cell)
        core = transformed.strip()
        if self._is_ipyai_magic(core):
            await self._arun_ipyai_magic(core)
            return
        send = transformed if transformed.rstrip("\n") != cell.rstrip("\n") else cell
        return super().run_cell(send, store_history=store_history)

    async def interact(self, loop=None, display_banner=None):
        while self.keep_running:
            print("\n", end="")
            try: code = await self.prompt_for_code()
            except EOFError:
                if (not self.confirm_exit) or ask_yes_no("Do you really want to exit ([y]/n)?", "y", "n"): self.ask_exit()
            else:
                if code: await self.arun_cell(code, store_history=True)

    async def _arun_ipyai_magic(self, code):
        ns = dict(self.user_ns)
        ns["get_ipython"] = lambda: self
        try: res = eval(compile(code, "<ipyai>", "eval"), ns)
        except SyntaxError:
            try: exec(compile(code, "<ipyai>", "exec"), ns)
            except Exception: self.showtraceback()
            return
        except Exception:
            self.showtraceback()
            return
        if inspect.iscoroutine(res):
            try: await res
            except Exception: self.showtraceback()

    def run_line_magic(self, name, line):
        "Dispatched from transformed %ipyai line magics."
        if name == "ipyai" and self._ipyai_extension is not None: return self._ipyai_extension.handle_line(line)

    async def run_cell_magic(self, name, line, cell):
        "Dispatched from transformed %%ipyai / `.` prompts."
        if name == "ipyai" and self._ipyai_extension is not None: await self._ipyai_extension.run_prompt(cell)

    def showtraceback(self, *a, **kw): traceback.print_exc(file=sys.stderr)

    def get_prompt_tokens(self):
        ext = getattr(self, "_ipyai_extension", None)
        if ext is not None and getattr(ext, "prompt_mode", False):
            from pygments.token import Token
            return [(Token.Prompt, "Pr ["), (Token.PromptNum, str(self.execution_count)), (Token.Prompt, "]: ")]
        return super().get_prompt_tokens()
