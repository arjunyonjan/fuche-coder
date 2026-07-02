#!/usr/bin/env python3
"""Bridge between MCP stdin/stdout and cascade daemon socket."""
import socket, sys

SOCKET_PATH = "/tmp/cascade-mcp.sock"

sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
try:
    sock.connect(SOCKET_PATH)
except (FileNotFoundError, ConnectionRefusedError):
    print('{"jsonrpc":"2.0","id":null,"error":{"code":-32000,"message":"Cascade daemon not running"}}', flush=True)
    sys.exit(1)

wf = sock.makefile("w", buffering=1)
rf = sock.makefile("r", buffering=1)

for line in sys.stdin:
    line = line.strip()
    if not line:
        continue
    wf.write(line + "\n")
    wf.flush()
    rline = rf.readline()
    if rline:
        print(rline.strip(), flush=True)
