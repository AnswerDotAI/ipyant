"stdio MCP server that bridges tool calls back to an in-kernel ToolSocketServer over a unix socket."
import asyncio, json, os, sys


class _SocketClient:
    def __init__(self, reader, writer):
        self.reader,self.writer,self.lock,self._id = reader,writer,asyncio.Lock(),0

    async def rpc(self, method, params=None):
        async with self.lock:
            self._id += 1
            mid = self._id
            self.writer.write((json.dumps(dict(id=mid, method=method, params=params or {})) + "\n").encode())
            await self.writer.drain()
            line = await self.reader.readline()
            if not line: raise RuntimeError("ipyai tool socket closed")
            msg = json.loads(line)
            if msg.get("error"): raise RuntimeError(msg["error"].get("message", "rpc error"))
            return msg.get("result")


async def _main():
    from mcp.server.lowlevel import Server
    from mcp.server.stdio import stdio_server
    from mcp.types import CallToolResult, TextContent, Tool

    sock_path = os.environ.get("IPYAI_MCP_SOCK")
    if not sock_path:
        print("IPYAI_MCP_SOCK not set", file=sys.stderr)
        sys.exit(1)
    reader,writer = await asyncio.open_unix_connection(sock_path)
    client = _SocketClient(reader, writer)
    tools = await client.rpc("list_tools")
    tool_objs = [Tool(name=o["name"], description=o.get("description") or "", inputSchema=o.get("inputSchema") or dict(type="object"))
        for o in tools]
    server = Server("ipyai")

    @server.list_tools()
    async def _list(): return tool_objs

    @server.call_tool()
    async def _call(name, arguments):
        res = await client.rpc("call_tool", dict(name=name, args=arguments or {}))
        content = [TextContent(type=o.get("type", "text"), text=o.get("text", "")) for o in (res.get("content") or [])]
        return CallToolResult(content=content, isError=bool(res.get("isError")))

    async with stdio_server() as (rx, tx):
        await server.run(rx, tx, server.create_initialization_options())


def main(): asyncio.run(_main())


if __name__ == "__main__": main()
