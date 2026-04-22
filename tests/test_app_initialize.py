"End-to-end test that actually runs IPyAIApp.initialize() against a real spawned kernel. Stops short of starting the interactive prompt loop but verifies every wiring step (kernel spawn, async client, shell subclass, bootstrap inject, extension load)."


def test_app_initialize_wires_full_stack(tmp_path, monkeypatch):
    import ipyai.core as core
    monkeypatch.setattr(core, "CONFIG_DIR", tmp_path)
    monkeypatch.setattr(core, "CONFIG_PATH", tmp_path/"config.json")
    monkeypatch.setattr(core, "SYSP_PATH", tmp_path/"sysp.txt")
    monkeypatch.setattr(core, "LOG_PATH", tmp_path/"exact-log.jsonl")

    from ipyai.app import IPyAIApp
    from ipyai.shell import IPyAIShell

    IPyAIShell.clear_instance()
    app = IPyAIApp()
    try:
        app.initialize(["--simple-prompt"])

        assert isinstance(app.shell, IPyAIShell), f"shell is {type(app.shell).__name__}, expected IPyAIShell"
        assert app._bridge is not None
        assert app.shell._ipyai_bridge is app._bridge

        ext = app.shell._ipyai_extension
        assert ext is not None, "ipyai extension should have loaded"
        assert ext.loaded

        import asyncio
        async def _check():
            names = set(await app._bridge.available_names(force=True))
            return names
        names = asyncio.get_event_loop().run_until_complete(_check())
        assert "pyrun" in names, f"pyrun missing from kernel ns: {names}"
    finally:
        try: app._finalize_kernel()
        except Exception: pass
        try:
            if app.kernel_manager and app.kernel_manager.is_alive(): app.kernel_manager.shutdown_kernel(now=True)
        except Exception: pass
        IPyAIShell.clear_instance()
