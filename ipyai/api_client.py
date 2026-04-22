import json, warnings

from litellm.types.utils import ModelResponse
from lisette.core import AsyncChat as LisetteAsyncChat, AsyncStreamFormatter as LisetteAsyncStreamFormatter, CodexChat, contents

from .backend_common import BaseBackend, ConversationSeed, compact_tool, seed_to_flat_history


class _BridgeNS(dict):
    "Dict-shaped proxy so lisette's ns-based tool-call path routes through the ToolRegistry bridge."
    def __init__(self, registry):
        super().__init__()
        self._reg = registry

    def __contains__(self, name): return False

    def get(self, name, default=None):
        async def _caller(**kwargs): return await self._reg.call_text(name, kwargs)
        _caller.__name__ = name
        return _caller

    def __getitem__(self, name): return self.get(name)


# litellm's responses-endpoint handler falls back to `model_construct` on chat/responses
# usage-shape mismatches, which later emits pydantic serializer warnings when the partially
# typed object is dumped. Upstream bug, harmless here.
warnings.filterwarnings("ignore", message="Pydantic serializer warnings", category=UserWarning)


class AsyncStreamFormatter(LisetteAsyncStreamFormatter):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.final_text = ""

    def format_item(self, o):
        if isinstance(o, ModelResponse):
            if tcs := getattr(contents(o), "tool_calls", None):
                self.tcs = {tc.id: tc for tc in tcs}
                return ""
        if isinstance(o, dict) and "tool_call_id" in o:
            if (tc := self.tcs.pop(o["tool_call_id"], None)) is not None:
                args = json.loads(tc.function.arguments or "{}")
                text = compact_tool(tc.function.name, args, o.get("content") or "")
                self.outp += text
                return text
        return super().format_item(o)

    async def format_stream(self, stream):
        async for chunk in super().format_stream(stream):
            self.final_text = self.outp
            yield chunk


class _LisetteBackend(BaseBackend):
    formatter_cls = AsyncStreamFormatter

    def _make_chat(self, **kw): raise NotImplementedError

    async def prepare_turn(self, *, prompt, model, think="l", provider_session_id=None, seed=None, tool_mode="on", ephemeral=False):
        seed = seed or ConversationSeed()
        tools = (await self.tools.openai_schemas()) or None if tool_mode != "off" else None
        ns = _BridgeNS(self.tools) if tool_mode != "off" else {}
        chat = self._make_chat(model=model, sp=self.ctx.system_prompt, hist=seed_to_flat_history(seed) or None, ns=ns, tools=tools)
        stream = await chat(prompt, stream=True, think=think, max_steps=21)
        return self.prepared_turn(stream, provider_session_id=provider_session_id)


class ClaudeAPIBackend(_LisetteBackend):
    def _make_chat(self, **kw): return LisetteAsyncChat(**kw, cache=True)


class CodexAPIBackend(_LisetteBackend):
    def _make_chat(self, **kw): return CodexChat(useasync=True, **kw)
