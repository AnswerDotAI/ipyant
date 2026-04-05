from lisette.core import AsyncChat as LisetteAsyncChat, AsyncStreamFormatter as LisetteAsyncStreamFormatter, contents

from .tooling import openai_tool_schemas


def _flatten_history(records):
    hist = []
    for _,_,full_prompt,response,_ in records or []:
        hist += [full_prompt, response if response.strip() else "<system>user interrupted</system>"]
    return hist


class AsyncStreamFormatter(LisetteAsyncStreamFormatter):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.final_text = ""

    async def format_stream(self, stream):
        async for chunk in super().format_stream(stream):
            self.final_text = self.outp
            yield chunk


class FullResponse(str):
    @property
    def content(self): return str(self)


class ClaudeAPIBackend:
    formatter_cls = AsyncStreamFormatter

    def __init__(self, shell=None, cwd=None, system_prompt="", plugin_dirs=None, cli_path=None):
        self.shell = shell
        self.cwd = cwd
        self.system_prompt = system_prompt

    @property
    def ns(self): return getattr(self.shell, "user_ns", {})

    async def bootstrap_session(self, *, model, think="l", session_id=None, records=None, events=None, state=None): return session_id

    async def complete(self, prompt, *, model):
        res = await LisetteAsyncChat(model=model, sp=self.system_prompt, cache=True)(prompt)
        return FullResponse((contents(res).content or "").strip())

    async def stream_turn(self, prompt, *, model, think="l", session_id=None, records=None, events=None, state=None):
        tools = openai_tool_schemas(self.ns) or None
        chat = LisetteAsyncChat(model=model, sp=self.system_prompt, hist=_flatten_history(records) or None, ns=self.ns, tools=tools, cache=True)
        stream = await chat(prompt, stream=True, think=think, max_steps=21)
        async for chunk in stream: yield chunk
