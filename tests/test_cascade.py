"""Test cascade AI daemon via JSON-RPC."""
import json, socket

def cascade_query(query):
    s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    s.settimeout(60)
    s.connect("/tmp/cascade-mcp.sock")
    s.sendall(json.dumps({"jsonrpc": "2.0", "id": 1, "method": "initialize"}).encode() + b"\n")
    s.recv(4096)
    s.sendall(json.dumps({"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": {"arguments": {"query": query}}}).encode() + b"\n")
    r = json.loads(s.recv(65535))
    s.close()
    return r

if __name__ == "__main__":
    r = cascade_query("say hello")
    meta = r["result"]["meta"]
    print(f"Model: {meta['model']}  Chain: {meta['chain']}  Elapsed: {meta['elapsed']}")
    print(f"Response: {r['result']['content'][0]['text'][:200]}")
