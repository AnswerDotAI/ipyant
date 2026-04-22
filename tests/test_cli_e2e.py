"End-to-end tests that spawn `ipyai` as a subprocess, pipe stdin, and assert on stdout. Each test owns one short session; we batch as many checks as possible inside each to keep kernel spawns few."
import os, subprocess, sys
from pathlib import Path

import pytest


def _ipyai(stdin_text, *args, env_extra=None, timeout=180, tmp_config=None, ipython_dir=None):
    env = os.environ.copy()
    if tmp_config is not None: env["XDG_CONFIG_HOME"] = str(tmp_config)
    if ipython_dir is not None: env["IPYTHONDIR"] = str(ipython_dir)
    if env_extra: env.update(env_extra)
    proc = subprocess.run([sys.executable, "-m", "ipyai.app", "--simple-prompt", *args],
        input=stdin_text, capture_output=True, text=True, env=env, timeout=timeout)
    return proc


@pytest.fixture
def isolated_config(tmp_path):
    cfg = tmp_path/"config"
    (cfg/"ipyai").mkdir(parents=True)
    ipython_dir = tmp_path/"ipython"
    ipython_dir.mkdir(parents=True)
    return cfg, ipython_dir


def test_ipyai_kernel_roundtrip_no_backend(isolated_config):
    "Kernel-only (no backend) checks: ;-prefix escape, %-line-magic, image dispatch to kittytgp."
    cfg, ipy = isolated_config
    (cfg/"ipyai"/"config.json").write_text('{"backend":"codex-api","prompt_mode":true}\n')
    stdin = (";1+2\n"
        "%matplotlib inline\n"
        ";import matplotlib.pyplot as plt; fig, ax = plt.subplots(); ax.plot([1,2,3]); fig\n"
        ";exit()\n")
    proc = _ipyai(stdin, tmp_config=cfg, ipython_dir=ipy)
    combined = proc.stdout + proc.stderr
    assert proc.returncode == 0, combined
    assert "3" in proc.stdout, f"kernel should evaluate 1+2 to 3: {proc.stdout!r}"
    assert "TypeError" not in proc.stdout, "kernel autocall on ;-prefix would produce TypeError"
    assert "TraitError" not in combined, f"image_handler Enum rejected dispatch value:\n{combined}"
    assert "Event loop is closed" not in proc.stderr, f"double-shutdown race on exit:\n{proc.stderr}"
    assert "was never awaited" not in proc.stderr, f"leaked kernel coroutine on shutdown:\n{proc.stderr}"


def test_ipyai_backend_roundtrip(isolated_config):
    "Backend checks: dot-prefix prompt and prompt-mode plain line both reach the backend; history persists across sessions."
    if not Path("~/.codex/auth.json").expanduser().exists(): pytest.skip("~/.codex/auth.json not present")
    cfg, ipy = isolated_config
    (cfg/"ipyai"/"config.json").write_text('{"backend":"codex-api","prompt_mode":true}\n')
    stdin = (".reply with exactly the word widget and nothing else\n"
        "reply with exactly the word sprocket and nothing else\n"
        ";exit()\n")
    proc = _ipyai(stdin, tmp_config=cfg, ipython_dir=ipy, timeout=300)
    out = proc.stdout.lower()
    assert proc.returncode == 0, proc.stderr
    assert "widget" in out, f"dot-prompt response missing 'widget': {out!r}"
    assert "sprocket" in out, f"prompt-mode sentence response missing 'sprocket': {out!r}"

    import sqlite3
    hist_path = Path(ipy)/"profile_default"/"history.sqlite"
    assert hist_path.exists(), f"expected shared history DB at {hist_path}"
    with sqlite3.connect(str(hist_path)) as db:
        prompts = [r[0] for r in db.execute("SELECT prompt FROM claude_prompts ORDER BY id").fetchall()]
    assert any("widget" in p for p in prompts), f"first prompt not persisted to shared DB: {prompts}"
    assert any("sprocket" in p for p in prompts), f"second prompt not persisted to shared DB: {prompts}"


def test_kernel_shuts_down_on_normal_exit(isolated_config):
    "Running ipyai (without --existing, without --keep-alive) and exiting should terminate the kernel subprocess."
    import time
    cfg, ipy = isolated_config
    (cfg/"ipyai"/"config.json").write_text('{"backend":"codex-api","prompt_mode":false}\n')

    proc = _ipyai(";exit()\n", tmp_config=cfg, ipython_dir=ipy, timeout=60)
    assert proc.returncode == 0
    time.sleep(0.5)
    ps = subprocess.run(["pgrep", "-f", f"ipykernel_launcher.*{ipy}"], capture_output=True, text=True)
    assert not ps.stdout.strip(), f"kernel subprocess still alive after ipyai exit: pids={ps.stdout!r}"
