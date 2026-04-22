from ipyai.backend_common import BaseBackend, COMPLETION_THINK, ConversationSeed
from ipyai.core import IPyAIExtension, LAST_RESPONSE
from ipyai.tooling import ToolRegistry


def test_tool_registry_exposes_provider_shapes(shell):
    def pyrun(code: str):
        "Execute code"
        return code

    shell.user_ns["pyrun"] = pyrun
    reg = ToolRegistry(shell.user_ns)

    assert reg.names() == ["pyrun"]
    assert reg.claude_allowed_tool_names() == ["mcp__ipy__pyrun"]
    tool = reg.codex_dynamic_tools()[0]
    assert tool["name"] == "pyrun"
    assert tool["description"] == "Execute code"
    assert tool["inputSchema"]["type"] == "object"
    assert tool["inputSchema"]["required"] == ["code"]
    assert tool["inputSchema"]["properties"]["code"]["type"] == "string"


def test_extension_conversation_seed_is_typed(shell):
    ext = IPyAIExtension(shell=shell)
    shell.history_manager.add(1, "x = 1")
    ext.save_prompt("what", "<user-request>what</user-request>", "answer", 1)

    seed = ext.conversation_seed()

    assert seed.turns[0].prompt == "what"
    assert seed.turns[0].full_prompt == "<user-request>what</user-request>"
    assert seed.startup_events[0].kind == "code"
    assert seed.startup_events[1].kind == "prompt"


class DummyBackend(BaseBackend):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.calls = []

    async def prepare_turn(self, **kwargs):
        self.calls.append(kwargs)
        if setter := kwargs.get("session_setter"): setter("sess_late")
        async def _stream(): yield "hello"

        turn = self.prepared_turn(_stream())
        if kwargs.get("provider_session_id") is None and kwargs.get("tool_mode") != "off": turn.set_provider_session_id("sess_late")
        return turn


async def test_base_backend_complete_enforces_tool_off_ephemeral_policy(shell):
    backend = DummyBackend(shell=shell)

    res = await backend.complete("hi", model="demo")

    assert str(res) == "hello"
    call = backend.calls[0]
    assert call["prompt"] == "hi"
    assert call["model"] == "demo"
    assert call["think"] == COMPLETION_THINK
    assert call["provider_session_id"] is None
    assert call["seed"] == ConversationSeed()
    assert call["tool_mode"] == "off"
    assert call["ephemeral"] is True


async def test_prepared_turn_exposes_late_provider_session_id(shell):
    backend = DummyBackend(shell=shell)
    turn = await backend.prepare_turn(prompt="hi", model="demo", think="l", provider_session_id=None, seed=ConversationSeed())

    text = "".join([o async for o in turn.stream])

    assert text == "hello"
    assert await turn.wait_provider_session_id() == "sess_late"


async def test_core_run_prompt_passes_conversation_seed(shell, monkeypatch):
    backend = DummyBackend(shell=shell)
    ext = IPyAIExtension(shell=shell, backend_factory=lambda **kwargs: backend)
    ext.load()
    shell.history_manager.add(1, "x = 1")
    shell.execution_count = 2

    async def _fake_astream_to_stdout(stream, **kwargs): return "".join([o async for o in stream])
    monkeypatch.setattr("ipyai.core.astream_to_stdout", _fake_astream_to_stdout)

    await ext.run_prompt("hello")

    seed = backend.calls[0]["seed"]
    assert isinstance(seed, ConversationSeed)
    assert seed.startup_events[0].kind == "code"
    assert shell.user_ns[LAST_RESPONSE] == "hello"
