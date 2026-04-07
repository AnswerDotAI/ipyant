from lisette.core import AsyncChat as LisetteAsyncChat, AsyncStreamFormatter as LisetteAsyncStreamFormatter

from .backend_common import BaseBackend, ConversationSeed, seed_to_flat_history


class AsyncStreamFormatter(LisetteAsyncStreamFormatter):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.final_text = ""

    async def format_stream(self, stream):
        async for chunk in super().format_stream(stream):
            self.final_text = self.outp
            yield chunk


class ClaudeAPIBackend(BaseBackend):
    formatter_cls = AsyncStreamFormatter

    async def prepare_turn(self, *, prompt, model, think="l", provider_session_id=None, seed=None, tool_mode="on", ephemeral=False):
        seed = seed or ConversationSeed()
        tools = self.tools.openai_schemas() or None if tool_mode != "off" else None
        ns = self.ns if tool_mode != "off" else {}
        chat = LisetteAsyncChat(model=model, sp=self.ctx.system_prompt, hist=seed_to_flat_history(seed) or None, ns=ns, tools=tools, cache=True)
        stream = await chat(prompt, stream=True, think=think, max_steps=21)
        return self.prepared_turn(stream, provider_session_id=provider_session_id)
