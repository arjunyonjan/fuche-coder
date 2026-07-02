#!/usr/bin/env python3
"""MCP server for model cascade — supports daemon mode."""
import json, sys, os, socket, threading
sys.path.insert(0, "/home/arjun/fuche-coder")
from cascade import cascade_answer

SOCKET_PATH = "/tmp/cascade-mcp.sock"

class Conn:
    def __init__(self, write, flush):
        self.write = write
        self.flush = flush

    def respond(self, msg_id, result):
        self.write(json.dumps({"jsonrpc": "2.0", "id": msg_id, "result": result}) + "\n")
        self.flush()

def handle_request(line, conn):
    line = line.strip()
    if not line:
        return
    try:
        msg = json.loads(line)
    except json.JSONDecodeError:
        return
    mid = msg.get("id")
    method = msg.get("method")
    if method == "initialize":
        conn.respond(mid, {"protocolVersion": "2024-11-05", "capabilities": {"tools": {}}, "serverInfo": {"name": "cascade", "version": "1.0.0"}})
    elif method == "listTools":
        conn.respond(mid, {
            "tools": [{
                "name": "cascade_query",
                "description": "Run a coding query through the 4-model cascade (Qwen->Ornith->Qwen Cloud->DeepSeek) with quality gate and RAG persistence",
                "inputSchema": {
                    "type": "object",
                    "properties": {"query": {"type": "string", "description": "The coding question or task"}},
                    "required": ["query"]
                }
            }]
        })
    elif method == "tools/call":
        args = msg.get("params", {}).get("arguments", {})
        query = args.get("query", "")
        try:
            content, model, chain, elapsed = cascade_answer(query)
            conn.respond(mid, {
                "content": [{"type": "text", "text": content}],
                "isError": False,
                "meta": {"model": model, "chain": " -> ".join(chain), "elapsed": f"{elapsed:.1f}s"}
            })
        except Exception as e:
            conn.respond(mid, {
                "content": [{"type": "text", "text": f"Cascade error: {e}"}],
                "isError": True,
                "meta": {"error": str(e)}
            })
    elif method == "notifications/initialized":
        pass

def handle_client(conn):
    w = conn.makefile("w", buffering=1)
    f = conn.makefile("r", buffering=1)
    c = Conn(lambda s: (w.write(s), w.flush()), w.flush)
    with conn, f, w:
        for line in f:
            handle_request(line, c)

def daemon_main():
    if os.path.exists(SOCKET_PATH):
        os.unlink(SOCKET_PATH)
    server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    server.bind(SOCKET_PATH)
    server.listen(5)
    os.chmod(SOCKET_PATH, 0o666)
    while True:
        conn, _ = server.accept()
        t = threading.Thread(target=handle_client, args=(conn,), daemon=True)
        t.start()

def stdio_main():
    c = Conn(sys.stdout.write, sys.stdout.flush)
    for line in sys.stdin:
        handle_request(line, c)

if __name__ == "__main__":
    if "--daemon" in sys.argv or "--serve" in sys.argv:
        daemon_main()
    else:
        stdio_main()
