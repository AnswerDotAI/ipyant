import asyncio, os, shutil, sqlite3, tempfile
from pathlib import Path
from types import SimpleNamespace

import pytest

TEST_HOME = Path(tempfile.mkdtemp(prefix="ipyant-tests-"))
os.environ["XDG_CONFIG_HOME"] = str(TEST_HOME/"xdg")
os.environ["CLAUDE_CONFIG_DIR"] = str(TEST_HOME/"claude")
os.environ["IPYTHONDIR"] = str(TEST_HOME/"ipython")

import ipyant.core as core
from ipyant.claude_client import FullResponse


class DummyDisplayPublisher:
    def __init__(self): self._is_publishing = False


class DummyInputTransformerManager:
    def __init__(self): self.cleanup_transforms = []


class DummyHistory:
    def __init__(self, session_number=1):
        self.session_number = session_number
        self.db = sqlite3.connect(":memory:")
        self.entries = {}
        self.input_hist_parsed = [""]
        self.input_hist_raw = [""]
        with self.db:
            self.db.execute("""CREATE TABLE sessions (
                session INTEGER PRIMARY KEY,
                start TIMESTAMP,
                end TIMESTAMP,
                num_cmds INTEGER DEFAULT 0,
                remark TEXT)""")
            self.db.execute("""CREATE TABLE history (
                session INTEGER,
                line INTEGER,
                source TEXT)""")
            self.db.execute("INSERT INTO sessions (session, start, end, num_cmds, remark) VALUES (?, CURRENT_TIMESTAMP, NULL, 0, ?)",
                (session_number, None))

    def add(self, line, source, output=None):
        self.entries[line] = (source, output)
        with self.db:
            self.db.execute("INSERT INTO history (session, line, source) VALUES (?, ?, ?)", (self.session_number, line, source))

    def get_range(self, session=0, start=1, stop=None, raw=True, output=False):
        if stop is None: stop = max(self.entries, default=0) + 1
        for i in range(start, stop):
            if i not in self.entries: continue
            src,out = self.entries[i]
            yield (0, i, (src, out) if output else src)


class DummyShell:
    def __init__(self):
        self.input_transformer_manager = DummyInputTransformerManager()
        self.user_ns = {}
        self.magics = []
        self.history_manager = DummyHistory()
        self.display_pub = DummyDisplayPublisher()
        self.execution_count = 1
        self.ran_cells = []
        self.loop_runner = asyncio.run
        self.prompts = SimpleNamespace(in_prompt_tokens=lambda: [])

    def register_magics(self, magics): self.magics.append(magics)
    def set_custom_exc(self, *args): pass

    def run_cell(self, source, store_history=False):
        self.ran_cells.append((source, store_history))
        result = None
        try:
            tree = compile(source, f"<cell-{self.execution_count}>", "exec")
            exec(tree, self.user_ns)
        except Exception as e: return SimpleNamespace(success=False, error_in_exec=e, result=None)
        if store_history:
            self.history_manager.add(self.execution_count, source)
            self.execution_count += 1
        return SimpleNamespace(success=True, result=result, error_in_exec=None, error_before_exec=None)

    async def run_cell_async(self, source, store_history=False, transformed_cell=None):
        return self.run_cell(transformed_cell or source, store_history=store_history)


class FakeBackend:
    calls = []

    def __init__(self, shell=None, cwd=None, system_prompt="", plugin_dirs=None, cli_path=None):
        self.shell,self.cwd,self.system_prompt = shell,cwd,system_prompt

    async def complete(self, prompt, *, model): return FullResponse(" + completion")

    async def stream_turn(self, prompt, *, model, think="l", resume=None, state=None):
        type(self).calls.append(dict(prompt=prompt, model=model, think=think, resume=resume, cwd=self.cwd))
        state["session_id"] = resume or f"fake-session-{len(type(self).calls)}"
        yield {"kind": "thinking_start"}
        yield {"kind": "thinking_delta", "delta": "working"}
        yield {"kind": "thinking_end"}
        if "factor" in prompt.lower():
            yield dict(kind="tool_start", id="t1", name="python", input={"code": "2*2*3*5"})
            yield dict(kind="tool_complete", id="t1", name="python", input={"code": "2*2*3*5"}, content="60", is_error=False)
            yield "60 = 2 * 2 * 3 * 5"
        else: yield "60"


@pytest.fixture(autouse=True)
def _test_env(tmp_path):
    old = Path.cwd()
    os.chdir(tmp_path)
    if core.CONFIG_DIR.exists(): shutil.rmtree(core.CONFIG_DIR)
    core.CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    FakeBackend.calls = []
    try: yield
    finally: os.chdir(old)


@pytest.fixture
def shell(): return DummyShell()
