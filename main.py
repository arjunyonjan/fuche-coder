#!/usr/bin/env python3
import hashlib
import json
import logging
import os
import sys
import time
import requests

logging.basicConfig(level=logging.INFO, format="%(message)s", stream=sys.stderr)
log = logging.getLogger(__name__)

OLLAMA = "http://localhost:11434/api/chat"
DDG_CHECK = "https://duckduckgo.com"

CODE_MODEL = "qwen3:0.6b"
GEN_MODEL = "alibayram/hunyuan:0.5b"

SYSTEM_PROMPT = "You are a helpful assistant. Provide accurate, concise, factual answers. If you don't know, say so."

TIME_SENSITIVE = {"latest", "current", "today", "news", "update", "new", "recent",
                  "2024", "2025", "2026", "2027", "2028", "election", "price", "weather"}
TTL_SHORT = 3600
TTL_LONG = 86400

CACHE_DIR = os.path.expanduser("~/.cache/fuche")
CACHE_PATH = os.path.join(CACHE_DIR, "search_cache.json")
CACHE_MAX = 50


class SearchCache:
    def __init__(self):
        self._memory = {}
        os.makedirs(CACHE_DIR, exist_ok=True)
        self._load_disk()

    def _load_disk(self):
        try:
            with open(CACHE_PATH) as f:
                data = json.load(f)
            now = time.time()
            for k, v in list(data.items()):
                if now - v.get("fetched_at", 0) > self._ttl(v.get("query", "")):
                    del data[k]
            self._disk = data
        except (FileNotFoundError, json.JSONDecodeError):
            self._disk = {}

    def _save_disk(self):
        if len(self._disk) > CACHE_MAX:
            oldest = sorted(self._disk.keys(), key=lambda k: self._disk[k]["fetched_at"])
            for k in oldest[:len(self._disk) - CACHE_MAX]:
                del self._disk[k]
        try:
            with open(CACHE_PATH, "w") as f:
                json.dump(self._disk, f)
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
            return entry["results"]
        entry = self._disk.get(key)
        if entry and now - entry["fetched_at"] < self._ttl(query):
            self._memory[key] = entry
            return entry["results"]
        return None

    def set(self, query, results):
        key = self._key(query)
        entry = {"query": query, "results": results, "fetched_at": time.time()}
        self._memory[key] = entry
        self._disk[key] = entry
        self._save_disk()

    def invalidate(self, query):
        key = self._key(query)
        self._memory.pop(key, None)
        self._disk.pop(key, None)
        self._save_disk()


cache = SearchCache()


def is_online():
    try:
        requests.get(DDG_CHECK, timeout=2)
        return True
    except requests.RequestException:
        return False


def ask(model, messages, temp=0.3, timeout=15):
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
                     'war', 'history', 'population', 'language', 'currency']
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
    if not force_refresh:
        cached = cache.get(query)
        if cached:
            log.info(f"  ↳ cache hit")
            return cached

    if not is_online():
        log.info("  ↳ offline — skipping web search")
        return None

    from crawler import search_and_extract
    try:
        results = search_and_extract(query)
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
        return ask(model, enhanced, temp)

    log.info("  ↳ no context — model only")
    return ask(model, history, temp)


def chat():
    code_history = [{"role": "system", "content": SYSTEM_PROMPT}]
    gen_history = [{"role": "system", "content": SYSTEM_PROMPT}]

    print("⚡ Fuche AI Coder — interactive chat")
    print("   Commands: /exit  /clear  /model  /refresh")
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
            print(f"  Code:    {CODE_MODEL}")
            print(f"  General: {GEN_MODEL}")
            continue
        if q.startswith("/refresh"):
            log.info("Refreshing cache for next query...")
            cache.invalidate(q[len("/refresh"):].strip())
            print("cache cleared for that query")
            continue

        is_code = is_code_question(q)
        if is_code:
            model = CODE_MODEL
            history = code_history
            badge = "💻 Code"
        else:
            model = GEN_MODEL
            history = gen_history
            badge = "🧠 Gen"

        history.append({"role": "user", "content": q})
        print(f"  [{badge} → {model}]")
        ans = ask_with_context(q, model, history, temp=0.2)
        print(f"  {ans}\n")
        history.append({"role": "assistant", "content": ans})


def single_question(q):
    if is_code_question(q):
        print("💻 Code → Qwen3:0.6b", file=sys.stderr)
        ans = ask_with_context(q, CODE_MODEL, [{"role": "user", "content": q}], temp=0.2)
    else:
        print("🧠 General → Hunyuan", file=sys.stderr)
        ans = ask_with_context(q, GEN_MODEL, [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": q}
        ], temp=0.2)
    print(ans)


if __name__ == "__main__":
    q = " ".join(sys.argv[1:]).strip()
    if q:
        single_question(q)
    else:
        chat()
