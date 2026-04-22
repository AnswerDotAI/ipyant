"Uses the session kernel fixture. Verifies tool-bridge dispatch, variable-ref reads, and iopub output buffer shape."
import asyncio


def test_bridge_runs_pyrun_and_reads_vars(kernel_bridge, kernel_loop):
    loop = kernel_loop

    async def _go():
        await kernel_bridge._exec("x = 41\ny = x + 1")

        val = await kernel_bridge.read_var("y")
        assert val == 42

        vals = await kernel_bridge.read_vars(["x", "y"])
        assert vals == {"x": 41, "y": 42}

        names = await kernel_bridge.available_names(force=True)
        assert "pyrun" in names, f"pyrun missing from {names}"

        result = await kernel_bridge.call_tool("pyrun", dict(code="2 + 3"))
        assert "5" in result

        schemas = await kernel_bridge.schemas()
        pyrun_schema = next(s for s in schemas if s["function"]["name"] == "pyrun")
        assert "parameters" in pyrun_schema["function"]

    loop.run_until_complete(_go())


def test_iopub_buffer_captures_stream_and_display(session_kernel):
    "Teeing iopub via install_iopub_tee populates the shell's output_buffer."
    from collections import defaultdict
    loop = session_kernel["loop"]
    client = session_kernel["client"]

    captured = defaultdict(str)

    def _append(ec, text):
        if text is None: return
        captured[ec] += text

    def _capture(msg):
        typ = msg.get("msg_type")
        content = msg.get("content") or {}
        parent = msg.get("parent_header") or {}
        ec = parent.get("execution_count") or content.get("execution_count")
        if typ == "stream": _append(ec, content.get("text"))
        elif typ == "execute_result":
            data = content.get("data") or {}
            if "text/plain" in data: _append(ec, data["text/plain"])

    async def _go():
        msg_id = client.execute("print('hello ipyai'); 5+5", silent=False, store_history=False)
        start = loop.time()
        while loop.time() - start < 10:
            try: msg = await asyncio.wait_for(client.get_iopub_msg(), timeout=0.5)
            except asyncio.TimeoutError: continue
            if msg["parent_header"].get("msg_id") != msg_id: continue
            _capture(msg)
            if msg["msg_type"] == "status" and msg["content"].get("execution_state") == "idle": break

    loop.run_until_complete(_go())

    joined = "".join(captured.values())
    assert "hello ipyai" in joined
    assert "10" in joined
