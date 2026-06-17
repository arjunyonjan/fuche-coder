import json
import os
import time

HIST_PATH = os.path.expanduser("~/.cache/fuche/history.jsonl")
MAX_DAYS = 30


class History:
    def __init__(self):
        os.makedirs(os.path.dirname(HIST_PATH), exist_ok=True)
        self._prune()

    def append(self, conv_id, role, content, model, context=None):
        entry = {"conv": conv_id, "role": role, "content": content[:2000],
                 "model": model, "ts": time.time()}
        if context:
            entry["context"] = context[:2000]
        with open(HIST_PATH, 'a') as f:
            f.write(json.dumps(entry) + '\n')

    def search(self, query, limit=10):
        query = query.lower()
        found = []
        try:
            with open(HIST_PATH) as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        e = json.loads(line)
                        content = e.get("content", "") or ""
                        context = e.get("context", "") or ""
                        text = (content + " " + context).lower()
                        if query in text:
                            found.append(e)
                    except json.JSONDecodeError:
                        continue
        except FileNotFoundError:
            pass
        return found[-limit:]

    def list_convs(self, limit=20):
        convs = {}
        try:
            with open(HIST_PATH) as f:
                for line in f:
                    try:
                        e = json.loads(line)
                        cid = e["conv"]
                        if cid not in convs:
                            convs[cid] = {"id": cid, "ts": e["ts"], "count": 0,
                                          "model": e["model"], "snippet": ""}
                        convs[cid]["count"] += 1
                        convs[cid]["ts"] = max(convs[cid]["ts"], e["ts"])
                        if e["role"] == "user" and not convs[cid]["snippet"]:
                            convs[cid]["snippet"] = e["content"][:80]
                    except Exception:
                        continue
        except FileNotFoundError:
            return []
        return sorted(convs.values(), key=lambda c: c["ts"], reverse=True)[:limit]

    def get_conv(self, conv_id):
        msgs = []
        try:
            with open(HIST_PATH) as f:
                for line in f:
                    try:
                        e = json.loads(line)
                        if e["conv"] == conv_id:
                            msgs.append(e)
                    except Exception:
                        continue
        except FileNotFoundError:
            pass
        return msgs

    def export_conv(self, conv_id):
        return json.dumps(self.get_conv(conv_id), indent=2)

    def _prune(self):
        cutoff = time.time() - MAX_DAYS * 86400
        try:
            with open(HIST_PATH) as f:
                lines = [line for line in f if line.strip()]
        except FileNotFoundError:
            return
        kept = [line for line in lines if json.loads(line).get("ts", 0) >= cutoff]
        if len(kept) < len(lines):
            with open(HIST_PATH, 'w') as f:
                f.writelines(kept)

    def stats(self):
        total = 0
        convs = set()
        try:
            with open(HIST_PATH) as f:
                for line in f:
                    try:
                        e = json.loads(line)
                        total += 1
                        convs.add(e["conv"])
                    except Exception:
                        continue
        except FileNotFoundError:
            pass
        return total, len(convs)
