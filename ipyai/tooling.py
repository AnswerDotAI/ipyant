import inspect, json

from toolslm.funccall import get_schema_nm


CUSTOM_TOOL_NAMES = ("pyrun", "bash", "start_bgterm", "write_stdin", "close_bgterm", "lnhashview_file", "exhash_file")


def _result_text(res): return res if isinstance(res, str) else json.dumps(res, ensure_ascii=False, default=str)


def available_tool_names(ns): return [o for o in CUSTOM_TOOL_NAMES if callable(ns.get(o))]


def openai_tool_schemas(ns):
    res = []
    for name in available_tool_names(ns):
        try: res.append(dict(type="function", function=get_schema_nm(name, ns, pname="parameters")))
        except Exception: continue
    return res


async def call_ns_tool(ns, name, args=None):
    fn = ns.get(name)
    if not callable(fn): raise NameError(f"{name!r} is not defined in the active IPython namespace")
    res = fn(**(args or {}))
    if inspect.isawaitable(res): res = await res
    return _result_text(res)


def sdk_mcp_tools(ns, sdk_tool):
    res = []
    for name in available_tool_names(ns):
        try: schema = get_schema_nm(name, ns)
        except Exception: continue

        @sdk_tool(schema["name"], schema["description"], schema["input_schema"])
        async def _tool(args, _name=name):
            try: return dict(content=[dict(type="text", text=await call_ns_tool(ns, _name, args))])
            except Exception as e: return dict(content=[dict(type="text", text=f"Error: {e}")], is_error=True)

        res.append(_tool)
    return res
