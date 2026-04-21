import json, re

from safepyrun import RunPython

from ipyai.backends import BACKEND_CLAUDE_API, BACKEND_CLAUDE_CLI
from ipyai.core import IPyAIExtension, LAST_RESPONSE


def _backend_model(backend_name):
    if backend_name == BACKEND_CLAUDE_CLI: return "haiku"
    if backend_name == BACKEND_CLAUDE_API: return "claude-haiku-4-5-20251001"
    return "gpt-5.4-mini"


async def _run_once(shell_cls, tmp_path, backend_name, model):
    shell = shell_cls()
    shell.user_ns["hidden"] = "walnut"
    shell.user_ns["pyrun"] = RunPython(g=shell.user_ns)
    ext = IPyAIExtension(shell=shell, backend_name=backend_name, model=model, completion_model=model)
    ext.load()
    await ext.run_prompt("Use the `pyrun` tool to evaluate `hidden`. Reply with the returned lowercase word only. Keep the response to one word.")

    first = shell.user_ns[LAST_RESPONSE].strip().lower()
    assert re.search(r"\bwalnut\b", first)
    remark = json.loads(shell.history_manager.db.execute("SELECT remark FROM sessions WHERE session=1").fetchone()[0])
    assert remark["backend"] == backend_name
    if backend_name != BACKEND_CLAUDE_API: assert remark.get("provider_session_id")

    path,_,_ = ext.save_notebook(tmp_path/"session")

    shell2 = shell_cls()
    shell2.user_ns["pyrun"] = RunPython(g=shell2.user_ns)
    ext2 = IPyAIExtension(shell=shell2, backend_name=backend_name, model=model, completion_model=model)
    ext2.load()
    ext2.load_notebook(path)
    await ext2.run_prompt("Reply with the exact lowercase word from the loaded notebook only. No punctuation.")

    second = shell2.user_ns[LAST_RESPONSE].strip().lower()
    assert re.search(r"\bwalnut\b", second)
    loaded = ext2.prompt_records()[0]
    assert loaded[1] == ext.prompt_records()[0][1]
    assert loaded[2] == ext.prompt_records()[0][2]
    assert loaded[3] == ext.prompt_records()[0][3]


async def _run_roundtrip(shell_cls, tmp_path, backend_name):
    model = _backend_model(backend_name)
    await _run_once(shell_cls, tmp_path, backend_name, model)

