#!/home/arjun/fuche-coder/venv/bin/python
"""KISS SSE streaming server for cascade — http://localhost:8089/stream?q=..."""
import sys, os, json
sys.path.insert(0, "/home/arjun/fuche-coder")
from cascade import cascade_stream
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs

class SSEHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        q = parse_qs(urlparse(self.path).query).get("q", [None])[0]
        if not q:
            self.send_response(400)
            self.end_headers()
            self.wfile.write(b'{"error":"missing ?q=..."}')
            return
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        for event in cascade_stream(q):
            self.wfile.write(f"data: {event}\n\n".encode())
            self.wfile.flush()

    def log_message(self, *a): pass

if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8089
    server = HTTPServer(("0.0.0.0", port), SSEHandler)
    print(f"SSE server on :{port}", file=sys.stderr)
    server.serve_forever()
