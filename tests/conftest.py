import sqlite3
from types import SimpleNamespace

import pytest

import ipyai.core as core


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
        self.loop_runner = None
        self.prompts = SimpleNamespace(in_prompt_tokens=lambda: [])

    def register_magics(self, magics): self.magics.append(magics)
    def set_custom_exc(self, *args): pass

    def run_cell(self, source, store_history=False):
        self.ran_cells.append((source, store_history))
        try: exec(compile(source, f"<cell-{self.execution_count}>", "exec"), self.user_ns)
        except Exception as e: return SimpleNamespace(success=False, error_in_exec=e, result=None)
        if store_history:
            self.history_manager.add(self.execution_count, source)
            self.execution_count += 1
        return SimpleNamespace(success=True, result=None, error_in_exec=None, error_before_exec=None)

    async def run_cell_async(self, source, store_history=False, transformed_cell=None):
        return self.run_cell(transformed_cell or source, store_history=store_history)


@pytest.fixture(autouse=True)
def temp_core_paths(tmp_path, monkeypatch):
    cfg = tmp_path/"config"
    cfg.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(core, "CONFIG_DIR", cfg)
    monkeypatch.setattr(core, "CONFIG_PATH", cfg/"config.json")
    monkeypatch.setattr(core, "SYSP_PATH", cfg/"sysp.txt")
    monkeypatch.setattr(core, "LOG_PATH", cfg/"exact-log.jsonl")
    yield


@pytest.fixture
def shell(): return DummyShell()
