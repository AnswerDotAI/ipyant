"In-kernel unix socket server for MCP bridge subprocess to forward tool calls into the live ToolRegistry."
import asyncio, json, os, tempfile
from pathlib import Path


def _tool_spec(schema):
    fn = schema.get("function", {})
    return dict(name=fn.get("name"), description=fn.get("description") or "",
        inputSchema=fn.get("parameters") or dict(type="object"))


class ToolSocketServer:
    def __init__(self, registry):
        self.registry = registry
        self.server = self.sock_path = self.sock_dir = None

    async def start(self):
        if self.server is not None: return self
        d = Path(tempfile.mkdtemp(prefix="ipyai-mcp-"))
        os.chmod(d, 0o700)
        self.sock_dir = d
        self.sock_path = str(d/"sock")
        self.server = await asyncio.start_unix_server(self._handle, path=self.sock_path)
        return self

    async def stop(self):
        srv,path,d = self.server,self.sock_path,self.sock_dir
        self.server = self.sock_path = self.sock_dir = None
        if srv is None: return
        srv.close()
        try: await srv.wait_closed()
        except Exception: pass
        if path:
            try: os.unlink(path)
            except FileNotFoundError: pass
        if d:
            try: os.rmdir(d)
            except Exception: pass

    async def _handle(self, reader, writer):
        try:
            while True:
                line = await reader.readline()
                if not line: break
                try: resp = await self._dispatch(json.loads(line))
                except Exception as e: resp = dict(id=None, error=dict(message=str(e)))
                writer.write((json.dumps(resp) + "\n").encode())
                await writer.drain()
        finally:
            writer.close()
            try: await writer.wait_closed()
            except Exception: pass

    async def _dispatch(self, msg):
        mid,method,params = msg.get("id"), msg.get("method"), msg.get("params") or {}
        if method == "list_tools":
            schemas = await self.registry.openai_schemas()
            return dict(id=mid, result=[_tool_spec(s) for s in schemas])
        if method == "call_tool":
            try:
                text = await self.registry.call_text(params["name"], params.get("args") or {})
                return dict(id=mid, result=dict(content=[dict(type="text", text=text)], isError=False))
            except Exception as e: return dict(id=mid, result=dict(content=[dict(type="text", text=f"Error: {e}")], isError=True))
        return dict(id=mid, error=dict(message=f"Unknown method: {method}"))
