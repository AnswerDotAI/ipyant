"Fast pure-unit tests: input transforms, session listing, CLI backend-default injection, and IPyAIHistory."
import json, os

from IPython.core.inputtransformer2 import TransformerManager

from ipyai.backends import BACKEND_CLAUDE_CLI, BACKEND_CODEX
from ipyai.cli import _default_backend
from ipyai.core import SESSIONS_TABLE, _list_sessions, _resume_command, prompt_from_lines, transform_dots
from ipyai.shell import IPyAIHistory


def test_prompt_from_lines_and_transform_dots():
    lines = [".plan this work\\\n", "in two steps\n"]
    assert prompt_from_lines(lines) == "plan this work\nin two steps\n"
    code = "".join(transform_dots([".hello\n", "world\n"]))
    assert "run_cell_magic('ipyai'" in code


def test_cleanup_transform_works_with_ipython_transformer():
    tm = TransformerManager()
    tm.cleanup_transforms.insert(1, transform_dots)
    code = tm.transform_cell(".Ask a question\\\nwith a newline")
    assert code == "get_ipython().run_cell_magic('ipyai', '', 'Ask a question\\nwith a newline\\n')\n"


def test_list_sessions_filters_backend(test_db):
    cwd = os.getcwd()
    with test_db:
        test_db.execute(f"INSERT INTO {SESSIONS_TABLE} (session, remark) VALUES (?, ?)",
            (2, json.dumps(dict(cwd=cwd, backend=BACKEND_CLAUDE_CLI))))
        test_db.execute(f"INSERT INTO {SESSIONS_TABLE} (session, remark) VALUES (?, ?)",
            (3, json.dumps(dict(cwd=cwd, backend=BACKEND_CODEX))))
        test_db.execute(f"INSERT INTO {SESSIONS_TABLE} (session, remark) VALUES (?, ?)",
            (4, json.dumps(dict(cwd="/tmp/elsewhere", backend=BACKEND_CLAUDE_CLI))))

    rows = _list_sessions(test_db, cwd, BACKEND_CLAUDE_CLI)

    assert [row[0] for row in rows] == [2]


def test_resume_command_uses_existing_connection_file_when_attached(tmp_path, monkeypatch):
    "In --existing mode, the resume hint must point at the connection file, not at a bogus `-r session_id` that won't rebuild the attached state."
    import ipyai.core as core
    (tmp_path/"config.json").write_text('{"backend":"codex-api"}\n')
    monkeypatch.setattr(core, "CONFIG_PATH", tmp_path/"config.json")
    cf = "/tmp/kernel-1234.json"

    assert _resume_command(5, "codex-api") == "ipyai -r 5"
    assert _resume_command(5, "claude-api") == "ipyai -b claude-api -r 5"
    assert _resume_command(5, "codex-api", existing=cf) == f"ipyai --existing={cf}"
    assert _resume_command(5, "claude-api", existing=cf) == f"ipyai -b claude-api --existing={cf}"


def test_default_backend_prepends_when_no_flag():
    assert _default_backend(["-p"], "claude-api") == ["-b", "claude-api", "-p"]
    assert _default_backend([], "codex-api") == ["-b", "codex-api"]


def test_default_backend_preserves_explicit_flag():
    for argv in [["-b", "codex"], ["-b=codex"], ["--backend", "codex"], ["--backend=codex"],
                 ["--IPyAIApp.backend=codex"], ["-p", "-b", "claude-cli"]]:
        assert _default_backend(argv, "claude-api") == argv, argv


def _seed_mixed_history(db):
    with db:
        db.execute("INSERT INTO sessions (session) VALUES (2)")
        db.execute("INSERT INTO history (session, line, source, source_raw) VALUES (1,1,'import pandas','import pandas')")
        db.execute("INSERT INTO history (session, line, source, source_raw) VALUES (1,2,'x = 42','x = 42')")
        db.execute("INSERT INTO claude_prompts (session, prompt, full_prompt, response, history_line) VALUES (1,'explain x','','',2)")
        db.execute("INSERT INTO claude_prompts (session, prompt, full_prompt, response, history_line) VALUES (2,'new session hi','','',0)")
        db.execute("INSERT INTO history (session, line, source, source_raw) VALUES (2,1,'2+1','2+1')")


def test_history_adapter_chronological_newest_first(test_db):
    _seed_mixed_history(test_db)
    hist = IPyAIHistory(test_db, session_number=2)
    assert list(hist.load_history_strings()) == ["2+1", "new session hi", "explain x", "x = 42", "import pandas"]


def test_history_adapter_filters_by_prompt_mode(test_db):
    _seed_mixed_history(test_db)
    mode = [None]
    hist = IPyAIHistory(test_db, session_number=2, mode_fn=lambda: mode[0])

    mode[0] = "prompt"; hist._loaded = False
    assert list(hist.load_history_strings()) == ["new session hi", "explain x"]

    mode[0] = "code"; hist._loaded = False
    assert list(hist.load_history_strings()) == ["2+1", "x = 42", "import pandas"]

    mode[0] = None; hist._loaded = False
    assert list(hist.load_history_strings()) == ["2+1", "new session hi", "explain x", "x = 42", "import pandas"]
