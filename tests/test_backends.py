import json, re

from ipyai.backends import BACKEND_CLAUDE_API, BACKEND_CLAUDE_CLI, BACKEND_CODEX_API
from ipyai.core import IPyAIExtension, LAST_RESPONSE, SESSIONS_TABLE
from tests.conftest import _make_test_db


def _backend_model(backend_name):
    if backend_name == BACKEND_CLAUDE_CLI: return "haiku"
    if backend_name == BACKEND_CLAUDE_API: return "claude-haiku-4-5-20251001"
    return "gpt-5.4-mini"


def _fresh_db_and_session():
    db = _make_test_db()
    with db: cur = db.execute(f"INSERT INTO {SESSIONS_TABLE} (session) VALUES (NULL)")
    return db, cur.lastrowid


async def _run_once(shell_cls, tmp_path, backend_name, model, kernel_bridge, loop):
    shell = shell_cls()
    await kernel_bridge._exec("hidden = 'walnut'")
    db1, sess1 = _fresh_db_and_session()
    ext = IPyAIExtension(shell=shell, backend_name=backend_name, model=model, completion_model=model,
        bridge=kernel_bridge, db=db1, session_number=sess1)
    ext.load()

    await ext.run_prompt("Use the `pyrun` tool to evaluate `hidden`. Reply with the returned lowercase word only. Keep the response to one word.")

    first = shell.user_ns[LAST_RESPONSE].strip().lower()
    assert re.search(r"\bwalnut\b", first)
    remark_row = ext.db.execute(f"SELECT remark FROM {SESSIONS_TABLE} WHERE session=?", (ext.session_number,)).fetchone()
    remark = json.loads(remark_row[0])
    assert remark["backend"] == backend_name
    if backend_name not in (BACKEND_CLAUDE_API, BACKEND_CODEX_API): assert remark.get("provider_session_id")

    path,_,_ = ext.save_notebook(tmp_path/"session")

    await kernel_bridge._exec("globals().pop('hidden', None)")
    ext.unload()

    shell2 = shell_cls()
    db2, sess2 = _fresh_db_and_session()
    ext2 = IPyAIExtension(shell=shell2, backend_name=backend_name, model=model, completion_model=model,
        bridge=kernel_bridge, db=db2, session_number=sess2)
    ext2.load()
    ext2.load_notebook(path)
    await ext2.run_prompt("Reply with the exact lowercase word from the loaded notebook only. No punctuation.")

    second = shell2.user_ns[LAST_RESPONSE].strip().lower()
    assert re.search(r"\bwalnut\b", second)
    loaded = ext2.prompt_records()[0]
    assert loaded[1] == ext.prompt_records()[0][1]
    assert loaded[2] == ext.prompt_records()[0][2]
    assert loaded[3] == ext.prompt_records()[0][3]


async def _run_roundtrip(shell_cls, tmp_path, backend_name, kernel_bridge, loop):
    model = _backend_model(backend_name)
    await _run_once(shell_cls, tmp_path, backend_name, model, kernel_bridge, loop)
