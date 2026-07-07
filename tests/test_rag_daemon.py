"""Test RAG search daemon: ingest via hot daemon + search query."""
import json, socket

def ingest(path="/mnt/c/Users/ACER/OneDrive/Obsidian Vault/"):
    s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    s.settimeout(60)
    s.connect("/tmp/search-daemon.sock")
    s.sendall(json.dumps({"cmd": "ingest", "path": path}).encode() + b"\n")
    r = json.loads(s.recv(65535))
    s.close()
    return r

def search(query, top_k=3):
    s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    s.settimeout(10)
    s.connect("/tmp/search-daemon.sock")
    s.sendall(json.dumps({"query": query, "top_k": top_k}).encode() + b"\n")
    r = json.loads(s.recv(65535))
    s.close()
    return r

if __name__ == "__main__":
    print("Ingest:", ingest())
    print("Search:", search("test"))
