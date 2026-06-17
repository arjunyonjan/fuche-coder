#!/usr/bin/env python3
import hashlib
import json
import logging
import os
import sys
import time
import requests

from history import History

logging.basicConfig(level=logging.INFO, format="%(message)s", stream=sys.stderr)
log = logging.getLogger(__name__)

OLLAMA = "http://localhost:11434/api/chat"
OLLAMA_TAGS = "http://localhost:11434/api/tags"
DDG_CHECK = "https://duckduckgo.com"

CACHE_DIR = os.path.expanduser("~/.cache/fuche")
CACHE_PATH = os.path.join(CACHE_DIR, "search_cache.jsonl")
CACHE_MAX = 200

class ModelConfig:
    def __init__(self):
        self.code = "qwen3:0.6b"
        self.general = "alibayram/hunyuan:0.5b"
        self.crawl = True
        self._load()

    def _load(self):
        p = os.path.join(CACHE_DIR, "models.json")
        try:
            with open(p) as f:
                d = json.load(f)
                self.code = d.get("code", self.code)
                self.general = d.get("general", self.general)
                self.crawl = d.get("crawl", self.crawl)
        except (FileNotFoundError, json.JSONDecodeError):
            pass
        if not self.code and not self.general:
            self.crawl = False

    def save(self):
        with open(os.path.join(CACHE_DIR, "models.json"), 'w') as f:
            json.dump({"code": self.code, "general": self.general, "crawl": self.crawl}, f)

    def set(self, code=None, general=None, crawl=None):
        if code is not None:
            self.code = code
        if general is not None:
            self.general = general
        if crawl is not None:
            self.crawl = crawl
        if not self.code and not self.general:
            self.crawl = False
        self.save()

    def pick(self, is_code):
        if is_code and self.code:
            return self.code
        if not is_code and self.general:
            return self.general
        return self.code or self.general or ""

    def list_ollama(self):
        try:
            resp = requests.get(OLLAMA_TAGS, timeout=5)
            if resp.status_code == 200:
                models_data = resp.json().get("models", [])
                result = []
                for m in sorted(models_data, key=lambda x: x["name"]):
                    size_gb = round(m["size"] / (1024**3), 1)
                    result.append({"name": m["name"], "size_gb": size_gb})
                return result
        except Exception:
            return []
        return []

models = ModelConfig()

SYSTEM_PROMPT = f"You are a helpful assistant. Provide accurate, concise, factual answers. If you don't know, say so.\nWorking directory: {os.getcwd()}"

TIME_SENSITIVE = {"latest", "current", "today", "news", "update", "new", "recent",
                  "2024", "2025", "2026", "2027", "2028", "election", "price", "weather"}
TTL_SHORT = 3600
TTL_LONG = 86400

class SearchCache:
    def __init__(self):
        self._memory = {}
        os.makedirs(CACHE_DIR, exist_ok=True)
        self._migrate_old_json()
        self._load_disk()
        self._prune()

    def _migrate_old_json(self):
        old_path = os.path.join(CACHE_DIR, "search_cache.json")
        if not os.path.exists(old_path):
            return
        try:
            with open(old_path) as f:
                data = json.load(f)
            with open(CACHE_PATH, 'a') as f:
                for entry in data.values():
                    f.write(json.dumps(entry) + '\n')
            os.remove(old_path)
        except (FileNotFoundError, json.JSONDecodeError, OSError):
            pass

    def _load_disk(self):
        self._disk = {}
        try:
            with open(CACHE_PATH) as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        entry = json.loads(line)
                        key = self._key(entry.get("query", ""))
                        self._disk[key] = entry
                    except (json.JSONDecodeError, KeyError):
                        continue
        except FileNotFoundError:
            self._disk = {}

    def _prune(self):
        now = time.time()
        before = len(self._disk)
        self._disk = {k: v for k, v in self._disk.items()
                      if now - v.get("fetched_at", 0) < self._ttl(v.get("query", ""))}
        if len(self._disk) < before:
            self._save_disk()

    def _save_disk(self):
        if len(self._disk) > CACHE_MAX:
            oldest = sorted(self._disk.values(), key=lambda e: e.get("accessed_at", e["fetched_at"]))
            for e in oldest[:len(self._disk) - CACHE_MAX]:
                self._disk.pop(self._key(e.get("query", "")), None)
        try:
            with open(CACHE_PATH, 'w') as f:
                for entry in self._disk.values():
                    f.write(json.dumps(entry) + '\n')
        except OSError:
            pass

    @staticmethod
    def _key(query):
        return hashlib.sha256(query.strip().lower().encode()).hexdigest()[:16]

    @staticmethod
    def _ttl(query):
        words = set(query.lower().split())
        return TTL_SHORT if words & TIME_SENSITIVE else TTL_LONG

    def get(self, query):
        key = self._key(query)
        now = time.time()
        entry = self._memory.get(key)
        if entry and now - entry["fetched_at"] < self._ttl(query):
            entry["accessed_at"] = now
            return entry["results"]
        entry = self._disk.get(key)
        if entry and now - entry["fetched_at"] < self._ttl(query):
            entry["accessed_at"] = now
            self._memory[key] = entry
            return entry["results"]
        return None

    def set(self, query, results):
        key = self._key(query)
        now = time.time()
        entry = {"query": query, "results": results, "fetched_at": now, "accessed_at": now}
        self._memory[key] = entry
        self._disk[key] = entry
        with open(CACHE_PATH, 'a') as f:
            f.write(json.dumps(entry) + '\n')

    def invalidate(self, query):
        key = self._key(query)
        self._memory.pop(key, None)
        self._disk.pop(key, None)
        self._save_disk()


cache = SearchCache()
hist = History()


def is_online():
    try:
        requests.get(DDG_CHECK, timeout=2)
        return True
    except requests.RequestException:
        return False


def ask(model, messages, temp=0.3, timeout=120):
    payload = {
        "model": model,
        "messages": messages,
        "stream": False,
        "options": {"temperature": temp}
    }
    try:
        resp = requests.post(OLLAMA, json=payload, timeout=timeout)
        if resp.status_code == 200:
            return resp.json().get("message", {}).get("content", "")
        return f"Error: HTTP {resp.status_code}"
    except requests.exceptions.Timeout:
        return "Error: Timed out. Ollama may be busy."
    except requests.exceptions.ConnectionError:
        return "Error: Cannot connect to Ollama. Run 'ollama serve'."
    except Exception as e:
        return f"Error: {e}"


def is_code_question(text):
    text_lower = text.lower().strip()
    general_terms = ['capital', 'country', 'city', 'state', 'president', 'king', 'queen',
                     'war', 'history', 'population', 'language', 'currency', 'tutorial',
                     'explain', 'what is', 'how to', 'overview', 'guide']
    for term in general_terms:
        if term in text_lower:
            return False
    code_phrases = ["write", "create", "implement", "generate", "code",
                    "function", "class", "react", "vue", "hook", "api", "fetch", "axios", "useEffect"]
    for phrase in code_phrases:
        if phrase in text_lower:
            return True
    prog_terms = ['const', 'let', 'var', 'import', 'export', 'return', '=>', 'async', 'await',
                  'promise', 'callback', 'debug', 'compile', 'build', 'npm', 'git', 'docker']
    for term in prog_terms:
        if term in text_lower:
            return True
    return False


def get_context(query, force_refresh=False):
    if not models.crawl:
        return None
    if not force_refresh:
        cached = cache.get(query)
        if cached:
            log.info("  ↳ cache hit")
            return cached

    if not is_online():
        log.info("  ↳ offline — skipping web search")
        return None

    from loop import self_heal
    try:
        results = self_heal(query, max_loops=3, verbose=False)
        if results:
            cache.set(query, results)
        return results
    except Exception as e:
        log.warning(f"  ↳ search failed: {e}")
        return None


def ask_with_context(query, model, history, temp=0.2):
    context = get_context(query)
    if context:
        enhanced = [
            {"role": "system", "content": f"Answer using this web context. If the context is not relevant, use your own knowledge.\n{context}"},
            {"role": "user", "content": query}
        ]
        return ask(model, enhanced, temp), context

    log.info("  ↳ no context — model only")
    return ask(model, history, temp), None


def chat():
    code_history = [{"role": "system", "content": SYSTEM_PROMPT}]
    gen_history = [{"role": "system", "content": SYSTEM_PROMPT}]
    conv_id = hashlib.sha256(str(time.time()).encode()).hexdigest()[:12]

    print("⚡ Fuche AI Coder — interactive chat")
    print("   Commands: /exit  /clear  /model  /refresh  /history  /search  /export")
    print()

    while True:
        try:
            q = input("> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break

        if not q:
            continue
        if q.startswith("/exit") or q.startswith("/quit"):
            break

        if q.startswith("/clear"):
            code_history = [{"role": "system", "content": SYSTEM_PROMPT}]
            gen_history = [{"role": "system", "content": SYSTEM_PROMPT}]
            print("cleared")
            continue

        if q.startswith("/model"):
            print(f"  Code:    {models.code}")
            print(f"  General: {models.general}")
            continue

        if q.startswith("/refresh"):
            log.info("Refreshing cache for next query...")
            cache.invalidate(q[len("/refresh"):].strip())
            print("cache cleared for that query")
            continue

        if q.startswith("/history"):
            parts = q.split(maxsplit=1)
            if len(parts) > 1:
                msgs = hist.get_conv(parts[1])
                if not msgs:
                    print("  no conversation found")
                    continue
                for m in msgs:
                    print(f"  {m['role']}: {m['content']}")
            else:
                convs = hist.list_convs()
                if not convs:
                    print("  no history yet")
                    continue
                for c in convs:
                    ts = time.strftime("%d %b %H:%M", time.localtime(c["ts"]))
                    print(f"  {c['id']}  {c['count']:>3} msgs  {ts}  {c['snippet']}")
            continue

        if q.startswith("/search"):
            query = q[len("/search"):].strip()
            if not query:
                print("  usage: /search <query>")
                continue
            results = hist.search(query)
            if not results:
                print("  no matches")
                continue
            for r in results:
                ts = time.strftime("%d %b %H:%M", time.localtime(r["ts"]))
                print(f"  [{r['conv'][:12]}] {ts} {r['role']}: {r['content'][:100]}")
            continue

        if q.startswith("/export"):
            parts = q.split(maxsplit=1)
            target = parts[1] if len(parts) > 1 else conv_id
            exported = hist.export_conv(target)
            print(exported)
            continue

        is_code = is_code_question(q)
        model = models.pick(is_code)
        history = code_history if is_code else gen_history
        badge = "💻 Coder" if is_code else "🧠 Reasoner"

        history.append({"role": "user", "content": q})
        print(f"  [{badge} → {model}]")
        ans, ctx = ask_with_context(q, model, history, temp=0.2)
        hist.append(conv_id, "user", q, model, context=ctx)
        print(f"  {ans}\n")
        history.append({"role": "assistant", "content": ans})
        hist.append(conv_id, "assistant", ans, model)


def single_question(q):
    is_code = is_code_question(q)
    model = models.pick(is_code)
    badge = "💻 Coder" if is_code else "🧠 Reasoner"
    print(f"{badge} → {model}", file=sys.stderr)
    hist = [{"role": "user", "content": q}] if is_code else [{"role": "system", "content": SYSTEM_PROMPT}, {"role": "user", "content": q}]
    ans, _ = ask_with_context(q, model, hist, temp=0.2)
    print(ans)


if __name__ == "__main__":
    q = " ".join(sys.argv[1:]).strip()
    if q:
        single_question(q)
    else:
        chat()
