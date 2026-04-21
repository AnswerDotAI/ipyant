import inspect, json

from toolslm.funccall import get_schema_nm


CUSTOM_TOOL_NAMES = ("pyrun", "bash", "start_bgterm", "write_stdin", "close_bgterm", "lnhashview_file", "exhash_file")


def _result_text(res): return res if isinstance(res, str) else json.dumps(res, ensure_ascii=False, default=str)


class ToolRegistry:
    def __init__(self, ns): self.ns = ns

    def names(self): return [o for o in CUSTOM_TOOL_NAMES if callable(self.ns.get(o))]

    def openai_schemas(self):
        res = []
        for name in self.names():
            try: res.append(dict(type="function", function=get_schema_nm(name, self.ns, pname="parameters")))
            except Exception: continue
        return res

    def codex_dynamic_tools(self):
        return [dict(name=o["function"]["name"], description=o["function"].get("description") or "",
            inputSchema=o["function"].get("parameters") or dict(type="object")) for o in self.openai_schemas()]

    def claude_allowed_tool_names(self, prefix="mcp__ipy__"): return [f"{prefix}{o}" for o in self.names()]

    async def call_text(self, name, args=None): return await call_ns_tool(self.ns, name, args)


def available_tool_names(ns): return ToolRegistry(ns).names()


def openai_tool_schemas(ns): return ToolRegistry(ns).openai_schemas()


async def call_ns_tool(ns, name, args=None):
    fn = ns.get(name)
    if not callable(fn): raise NameError(f"{name!r} is not defined in the active IPython namespace")
    res = fn(**(args or {}))
    if inspect.isawaitable(res): res = await res
    return _result_text(res)
