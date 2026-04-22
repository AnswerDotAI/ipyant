"IPyAIHistory: given a DB with rows in `history` (code) and `claude_prompts` (AI prompts), load_history_strings yields both, deduped, oldest-first. Also verifies the kernel's own shutdown-on-exit behaviour."
from ipyai.shell import IPyAIHistory


def _seed_mixed_history(db):
    with db:
        db.execute("INSERT INTO sessions (session) VALUES (2)")
        db.execute("INSERT INTO history (session, line, source, source_raw) VALUES (1,1,'import pandas','import pandas')")
        db.execute("INSERT INTO history (session, line, source, source_raw) VALUES (1,2,'x = 42','x = 42')")
        db.execute("INSERT INTO claude_prompts (session, prompt, full_prompt, response, history_line) VALUES (1,'explain x','','',2)")
        db.execute("INSERT INTO claude_prompts (session, prompt, full_prompt, response, history_line) VALUES (2,'new session hi','','',0)")
        db.execute("INSERT INTO history (session, line, source, source_raw) VALUES (2,1,'2+1','2+1')")


def test_history_adapter_chronological_newest_first(test_db):
    "Mixed-mode (no filter): both kinds interleaved chronologically, newest-first."
    _seed_mixed_history(test_db)
    hist = IPyAIHistory(test_db, session_number=2)
    entries = list(hist.load_history_strings())
    assert entries == ["2+1", "new session hi", "explain x", "x = 42", "import pandas"], entries


def test_history_adapter_filters_by_prompt_mode(test_db):
    "mode_fn='prompt' yields only claude_prompts; mode_fn='code' yields only history."
    _seed_mixed_history(test_db)

    mode = [None]
    hist = IPyAIHistory(test_db, session_number=2, mode_fn=lambda: mode[0])

    mode[0] = "prompt"
    hist._loaded = False
    assert list(hist.load_history_strings()) == ["new session hi", "explain x"]

    mode[0] = "code"
    hist._loaded = False
    assert list(hist.load_history_strings()) == ["2+1", "x = 42", "import pandas"]

    mode[0] = None
    hist._loaded = False
    assert list(hist.load_history_strings()) == ["2+1", "new session hi", "explain x", "x = 42", "import pandas"]


def test_kernel_shuts_down_on_normal_exit(tmp_path):
    "Running ipyai (without --existing, without --keep-alive) and exiting should terminate the kernel subprocess."
    import os, subprocess, sys, time
    cfg = tmp_path/"config"
    (cfg/"ipyai").mkdir(parents=True)
    (cfg/"ipyai"/"config.json").write_text('{"backend":"codex-api","prompt_mode":false}\n')
    ipy = tmp_path/"ipython"; ipy.mkdir()
    env = os.environ.copy()
    env["XDG_CONFIG_HOME"] = str(cfg)
    env["IPYTHONDIR"] = str(ipy)

    proc = subprocess.run([sys.executable, "-m", "ipyai.app", "--simple-prompt"],
        input=";exit()\n", capture_output=True, text=True, env=env, timeout=60)

    assert proc.returncode == 0
    time.sleep(0.5)
    ps = subprocess.run(["pgrep", "-f", f"ipykernel_launcher.*{ipy}"], capture_output=True, text=True)
    assert not ps.stdout.strip(), f"kernel subprocess still alive after ipyai exit: pids={ps.stdout!r}"
