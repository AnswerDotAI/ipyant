import json, os

from IPython.core.inputtransformer2 import TransformerManager

from ipyai.backends import BACKEND_CLAUDE_CLI, BACKEND_CODEX
from ipyai.core import SESSIONS_TABLE, _list_sessions, prompt_from_lines, transform_dots


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
