import json, socket, time

while True:
    try:
        s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        s.settimeout(30)
        s.connect("/tmp/search-daemon.sock")
        s.sendall(json.dumps({"cmd": "ingest", "path": "/mnt/c/Users/ACER/OneDrive/Obsidian Vault/"}).encode() + b"\n")
        r = json.loads(s.recv(65535))
        s.close()
        print("[%s] auto-ingest (%s)" % (time.strftime("%H:%M:%S"), r.get("status", "?")))
    except Exception as e:
        print("[%s] auto-ingest failed: %s" % (time.strftime("%H:%M:%S"), e))
    time.sleep(3600)
