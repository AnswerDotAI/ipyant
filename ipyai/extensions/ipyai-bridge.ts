import net from "node:net";
import { randomUUID } from "node:crypto";
import type { ExtensionAPI } from "@mariozechner/pi-coding-agent";
import { Type } from "@sinclair/typebox";

type BridgeTool = { name: string; description?: string; parameters?: any };
type Pending = { resolve: (value: any) => void; reject: (error: Error) => void; timer?: ReturnType<typeof setTimeout> };

const SOCKET_PATH = process.env.IPYAI_PI_TOOL_SOCKET;
const TIMEOUT_MS = Number(process.env.IPYAI_PI_TOOL_TIMEOUT_MS || 120000);

export default function ipyaiBridge(pi: ExtensionAPI) {
  if (!SOCKET_PATH) return;

  const pending = new Map<string, Pending>();
  const registered = new Set<string>();
  let socket: net.Socket | null = null;
  let buffer = "";

  const rejectAll = (message: string) => {
    const err = new Error(message);
    for (const [id, item] of pending.entries()) {
      if (item.timer) clearTimeout(item.timer);
      item.reject(err);
      pending.delete(id);
    }
  };

  const send = (obj: any) => {
    if (!socket || socket.destroyed) throw new Error("ipyai bridge socket is not connected");
    socket.write(JSON.stringify(obj) + "\n");
  };

  const parseLines = (chunk: Buffer | string) => {
    buffer += typeof chunk === "string" ? chunk : chunk.toString("utf8");
    while (true) {
      const idx = buffer.indexOf("\n");
      if (idx === -1) break;
      let line = buffer.slice(0, idx);
      buffer = buffer.slice(idx + 1);
      if (line.endsWith("\r")) line = line.slice(0, -1);
      if (!line.trim()) continue;
      try {
        const msg = JSON.parse(line);
        handleMessage(msg);
      } catch {
        continue;
      }
    }
  };

  const wrapParameters = (schema: any) => {
    if (!schema || typeof schema !== "object") return Type.Object({});
    return Type.Unsafe(schema);
  };

  const registerTools = (tools: BridgeTool[]) => {
    for (const tool of tools) {
      if (!tool?.name || registered.has(tool.name)) continue;
      registered.add(tool.name);
      const parameters = wrapParameters(tool.parameters);
      pi.registerTool({
        name: tool.name,
        label: tool.name,
        description: tool.description || `Call Python tool ${tool.name}`,
        parameters,
        async execute(_toolCallId, params) {
          const id = randomUUID();
          const resultPromise = new Promise<any>((resolve, reject) => {
            const timer = setTimeout(() => {
              pending.delete(id);
              reject(new Error(`Tool call timed out: ${tool.name}`));
            }, TIMEOUT_MS);
            pending.set(id, { resolve, reject, timer });
          });
          send({ type: "tool_call", id, name: tool.name, args: params || {} });
          const result = await resultPromise;
          return {
            content: Array.isArray(result?.content) ? result.content : [{ type: "text", text: String(result?.error || "") }],
            details: result?.details,
            isError: Boolean(result?.isError),
          };
        },
      });
    }
  };

  const handleMessage = (msg: any) => {
    if (msg?.type === "register_tools") {
      registerTools(Array.isArray(msg.tools) ? msg.tools : []);
      return;
    }
    if (msg?.type === "tool_result" && msg.id) {
      const item = pending.get(msg.id);
      if (!item) return;
      pending.delete(msg.id);
      if (item.timer) clearTimeout(item.timer);
      item.resolve(msg);
    }
  };

  pi.on("session_start", () => {
    if (socket && !socket.destroyed) return;
    socket = net.createConnection(SOCKET_PATH);
    socket.on("data", parseLines);
    socket.on("error", () => rejectAll("ipyai bridge socket error"));
    socket.on("close", () => rejectAll("ipyai bridge socket closed"));
  });

  pi.on("session_shutdown", () => {
    rejectAll("session shutdown");
    if (socket && !socket.destroyed) socket.destroy();
    socket = null;
  });
}
