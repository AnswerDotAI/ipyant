import json, os

from IPython.core.inputtransformer2 import TransformerManager

from ipyai.backends import BACKEND_CLAUDE_CLI, BACKEND_CODEX
from ipyai.core import _ensure_default_user_tools, _list_sessions, prompt_from_lines, transform_dots


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


def test_list_sessions_filters_backend(shell):
    db = shell.history_manager.db
    with db:
        db.execute("UPDATE sessions SET remark=? WHERE session=1", (json.dumps(dict(cwd=os.getcwd(), backend=BACKEND_CLAUDE_CLI)),))
        db.execute("INSERT INTO sessions (session, start, end, num_cmds, remark) VALUES (2, CURRENT_TIMESTAMP, NULL, 0, ?)",
            (json.dumps(dict(cwd=os.getcwd(), backend=BACKEND_CODEX)),))
        db.execute("INSERT INTO sessions (session, start, end, num_cmds, remark) VALUES (3, CURRENT_TIMESTAMP, NULL, 0, ?)",
            (json.dumps(dict(cwd="/tmp/elsewhere", backend=BACKEND_CLAUDE_CLI)),))

    rows = _list_sessions(db, os.getcwd(), BACKEND_CLAUDE_CLI)

    assert [row[0] for row in rows] == [1]


def test_default_user_tools_seed_new_tool_names(shell):
    _ensure_default_user_tools(shell)
    names = set(shell.user_ns)
    assert {"bash", "start_bgterm", "write_stdin", "close_bgterm", "lnhashview_file", "exhash_file"} <= names
    assert {"doc", "ex", "sed"}.isdisjoint(names)
