import asyncio, io, json, os

from IPython.core.inputtransformer2 import TransformerManager
from claude_agent_sdk import get_session_messages

from ipyant.core import (EXTENSION_NS, IPyAIExtension, LAST_PROMPT, LAST_RESPONSE, SOLVEIT_REPLY_SEP, astream_to_stdout, prompt_from_lines,
    resume_session, transform_dots)
from conftest import FakeBackend


class DummyAsyncFormatter:
    async def format_stream(self, stream):
        async for o in stream: yield o


class DummyMarkdown:
    def __init__(self, text, **kwargs): self.text,self.kwargs = text,kwargs


class DummyConsole:
    def __init__(self, **kwargs):
        self.kwargs = kwargs
        self.printed = []

    def print(self, obj):
        self.printed.append(obj)
        self.kwargs["file"].write(f"RICH:{obj.text}")


class DummyLive:
    instances = []

    def __init__(self, renderable, **kwargs):
        self.kwargs = kwargs
        self.renderables = [renderable]
        type(self).instances.append(self)

    def __enter__(self): return self
    def __exit__(self, exc_type, exc, tb): self.kwargs["console"].print(self.renderables[-1])
    def update(self, renderable, refresh=False): self.renderables.append(renderable)


class TTYStringIO(io.StringIO):
    def isatty(self): return True


async def _chunks(*items):
    for o in items: yield o


def mk_ext(shell, load=True, **kwargs):
    ext = IPyAIExtension(shell=shell, backend_factory=FakeBackend, **kwargs)
    return ext.load() if load else ext


def test_prompt_from_lines_and_transform_dots():
    lines = [".plan this work\\\n", "in two steps\n"]
    assert prompt_from_lines(lines) == "plan this work\nin two steps\n"
    code = "".join(transform_dots([".hello\n", "world\n"]))
    assert "run_cell_magic('ipyant'" in code


def test_astream_to_stdout_live_markdown():
    out = TTYStringIO()
    text = asyncio.run(astream_to_stdout(_chunks("a", "b"), formatter_cls=DummyAsyncFormatter, out=out, code_theme="github-dark",
        console_cls=DummyConsole, markdown_cls=DummyMarkdown, live_cls=DummyLive))
    assert text == "ab"
    md = DummyLive.instances[-1].renderables[-1]
    assert md.text == "ab"
    assert md.kwargs == dict(code_theme="github-dark", inline_code_theme="github-dark", inline_code_lexer="python")


def test_extension_load_and_status(shell, capsys):
    ext = mk_ext(shell)
    assert shell.user_ns[EXTENSION_NS] is ext
    ext.handle_line("")
    out = capsys.readouterr().out
    assert "self.model='sonnet'" in out
    assert "LOG_PATH=" in out


def test_save_and_load_require_filenames(shell, capsys):
    ext = mk_ext(shell)
    ext.handle_line("save")
    assert capsys.readouterr().out == "Usage: %ipyant save <filename>\n"
    ext.handle_line("load")
    assert capsys.readouterr().out == "Usage: %ipyant load <filename>\n"


async def test_run_prompt_stores_prompt_and_provider_session(shell):
    shell.history_manager.add(1, "x = 1")
    shell.execution_count = 2
    ext = mk_ext(shell)
    await ext.run_prompt("Pick a number")

    records = ext.prompt_records()
    assert len(records) == 1
    _,prompt,full_prompt,response,history_line = records[0]
    assert prompt == "Pick a number"
    assert "<context><code>x = 1</code></context>" in full_prompt
    assert response.endswith("60")
    assert history_line == 1
    assert shell.user_ns[LAST_PROMPT] == "Pick a number"
    assert shell.user_ns[LAST_RESPONSE].endswith("60")
    remark = shell.history_manager.db.execute("SELECT remark FROM sessions WHERE session=1").fetchone()[0]
    assert json.loads(remark) == dict(cwd=os.getcwd(), provider="claude", provider_session_id="fake-session-1")


async def test_notebook_roundtrip_and_synthetic_session_resume_e2e(shell, tmp_path):
    shell.history_manager.add(1, "n = 60")
    shell.execution_count = 2
    ext = mk_ext(shell)
    await ext.run_prompt("Pick a number")
    nb_path,_,_ = ext.save_notebook(tmp_path/"session")
    nb = json.loads(nb_path.read_text())
    prompt_cell = next(c for c in nb["cells"] if c["cell_type"] == "markdown" and c["metadata"].get("solveit_ai"))
    assert nb["metadata"]["solveit_ver"] == 2
    assert nb["metadata"]["solveit_dialog_mode"] == "standard"
    assert prompt_cell["source"] == "Pick a number" + SOLVEIT_REPLY_SEP + ext.prompt_records()[0][3]

    shell2 = type(shell)()
    ext2 = mk_ext(shell2)
    ext2.load_notebook(nb_path)
    assert ext2.prompt_records()[0][1:4] == ("Pick a number", ext.prompt_records()[0][2], ext.prompt_records()[0][3])
    assert ext2.get_provider_session_id() is None

    await ext2.run_prompt("Now factor it")
    session_id = ext2.get_provider_session_id()
    msgs = get_session_messages(session_id, directory=str(tmp_path))
    assert msgs[0].message["content"] == ext.prompt_records()[0][2]
    assert msgs[1].message["content"][0]["text"] == "60"
    assert FakeBackend.calls[-1]["resume"] == session_id
    assert ext2.prompt_rows()[-1][1].endswith("60 = 2 * 2 * 3 * 5")


def test_cleanup_transform_works_with_ipython_transformer():
    tm = TransformerManager()
    tm.cleanup_transforms.insert(1, transform_dots)
    code = tm.transform_cell(".Ask a question\\\nwith a newline")
    assert code == "get_ipython().run_cell_magic('ipyant', '', 'Ask a question\\nwith a newline\\n')\n"


def test_resume_session_deletes_fresh_session_row(shell):
    shell.history_manager.db.execute("INSERT INTO sessions (session, start, end, num_cmds, remark) VALUES (2, CURRENT_TIMESTAMP, NULL, 0, ?)", (None,))
    shell.history_manager.db.execute("INSERT INTO history (session, line, source) VALUES (1, 1, 'x = 1')")
    shell.history_manager.db.execute("UPDATE sessions SET remark=? WHERE session=2",
        (json.dumps(dict(cwd="/tmp/x", provider="claude", provider_session_id="fresh-session")),))
    shell.history_manager.session_number = 2
    shell.execution_count = 1

    resume_session(shell, 1)

    assert shell.history_manager.db.execute("SELECT * FROM sessions WHERE session=2").fetchone() is None


def test_reset_clears_provider_metadata_from_remark(shell):
    ext = mk_ext(shell)
    ext.set_provider_session("fake-session-1")
    ext.reset_session_history()

    remark = shell.history_manager.db.execute("SELECT remark FROM sessions WHERE session=1").fetchone()[0]
    assert json.loads(remark) == {"cwd": os.getcwd()}
