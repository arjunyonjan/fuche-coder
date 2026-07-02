#!/usr/bin/env python3
"""Model cascade with task routing + quality gate + sub-index RAG persistence."""
import json, os, re, socket, subprocess, sys, time, urllib.request, urllib.error
from search import search as _search, ingest_directory as _ingest

OLLAMA = "http://localhost:11434"
DEEPSEEK_API = "https://api.deepseek.com/v1/chat/completions"
DEEPSEEK_KEY = os.environ.get("DEEPSEEK_KEY", "")
if not DEEPSEEK_KEY:
    cfg_path = os.path.expanduser("~/.fuche/config.json")
    if os.path.exists(cfg_path):
        DEEPSEEK_KEY = json.load(open(cfg_path)).get("deepseek_key", "")
CODES_MD = "/mnt/c/Users/ACER/OneDrive/docs/codes.md"
CODES_MD_FALLBACK = os.path.expanduser("~/codes.md")
BASE_RAG = os.path.expanduser("~/.fuche")
SEARCH_SOCKET = "/tmp/search-daemon.sock"

MODELS = {
    "qwen":    {"name": "qwen3:0.6b",  "aliases": ["qwen3:0.6b-q4_K_M"], "think": False, "num_predict": 2048},
    "ornith":  {"name": "hf.co/AlexAtomic/ornith-9b-GGUF:Q4_K_M", "aliases": ["ornith-32k:latest"], "think": False, "num_predict": 4096},
    "qcloud":  {"name": "qwen3-coder-next:cloud", "aliases": ["qwen3-coder:480b-cloud"], "think": False, "num_predict": 4096},
    "ds":      {"name": "deepseek-v4-flash-free", "aliases": ["deepseek-v4-flash"], "think": False, "num_predict": 4096},
    "ds-paid": {"name": "deepseek-v4-flash", "api": True, "think": False, "num_predict": 4096, "paid": True},
}

def verify_models():
    for k in ["HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy"]:
        os.environ.pop(k, None)
    try:
        req = urllib.request.Request(f"{OLLAMA}/api/tags")
        resp = urllib.request.urlopen(req, timeout=5)
        available = [m["name"] for m in json.loads(resp.read()).get("models", [])]
    except Exception:
        print("  ⚠ Cannot reach Ollama — models not verified", file=sys.stderr)
        return
    for key, cfg in list(MODELS.items()):
        if key in CLOUD_ONLY:
            continue  # skip Ollama check for cloud-only models
        if cfg["name"] in available:
            continue
        found = None
        for alias in cfg.get("aliases", []):
            if alias in available:
                found = alias
                break
        if found:
            print(f"  [{key}] {cfg['name']} not found, using fallback {found}", file=sys.stderr)
            cfg["name"] = found
        else:
            print(f"  [{key}] {cfg['name']} NOT AVAILABLE — removing from cascade", file=sys.stderr)
            del MODELS[key]

def get_loaded_ollama_models():
    """Check which models are actually loaded in Ollama memory."""
    try:
        req = urllib.request.Request(f"{OLLAMA}/api/ps", method="GET")
        resp = urllib.request.urlopen(req, timeout=5)
        data = json.loads(resp.read())
        return {m["name"].split(":")[0] for m in data.get("models", [])}
    except (urllib.error.URLError, json.JSONDecodeError, KeyError):
        return set()
CLOUD_ONLY = {"ds", "ds-paid"}  # models that never run locally, skip Ollama check
BUDGET_FILE = os.path.expanduser("~/.fuche/budget.json")
DAILY_LIMIT = 0.10
HOURLY_LIMIT = 0.01
DS_INPUT_PRICE = 0.15 / 1_000_000
DS_OUTPUT_PRICE = 0.60 / 1_000_000

def budget_check():
    now = time.time()
    bgt = {"date": time.strftime("%Y-%m-%d"), "spent": 0, "hourly_start": now, "hourly_spent": 0}
    if os.path.exists(BUDGET_FILE):
        bgt.update(json.load(open(BUDGET_FILE)))
    if bgt["date"] != time.strftime("%Y-%m-%d"):
        bgt["date"], bgt["spent"] = time.strftime("%Y-%m-%d"), 0
    if now - bgt["hourly_start"] > 3600:
        bgt["hourly_start"], bgt["hourly_spent"] = now, 0
    return bgt["spent"] < DAILY_LIMIT and bgt["hourly_spent"] < HOURLY_LIMIT

def budget_spend(input_tok, output_tok):
    cost = input_tok * DS_INPUT_PRICE + output_tok * DS_OUTPUT_PRICE
    now = time.time()
    bgt = {"date": time.strftime("%Y-%m-%d"), "spent": 0, "hourly_start": now, "hourly_spent": 0}
    if os.path.exists(BUDGET_FILE):
        bgt.update(json.load(open(BUDGET_FILE)))
    if bgt["date"] != time.strftime("%Y-%m-%d"):
        bgt["date"], bgt["spent"] = time.strftime("%Y-%m-%d"), 0
    if now - bgt["hourly_start"] > 3600:
        bgt["hourly_start"], bgt["hourly_spent"] = now, 0
    bgt["spent"] = round(bgt["spent"] + cost, 6)
    bgt["hourly_spent"] = round(bgt["hourly_spent"] + cost, 6)
    json.dump(bgt, open(BUDGET_FILE, "w"))
    return cost

def compress_query(query):
    try:
        s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        s.settimeout(5)
        s.connect(SEARCH_SOCKET)
        s.sendall(json.dumps({"query": query, "top_k": 3}).encode() + b"\n")
        r = b""
        while b"\n" not in r:
            r += s.recv(4096)
        data = json.loads(r.decode().strip())
        s.close()
        if data.get("results") and data["results"][0]["kw"] >= 0.7:
            return True, data["results"][0]
        return False, None
    except Exception:
        return False, None

LABELS = {"qwen":"Qwen","ornith":"Ornith","qcloud":"Qwen Cloud","ds":"DeepSeek", "ds-paid": "DeepSeek Paid"}
CODE_KEYWORDS = ["def ", "class ", "function", "=>", "import ", "fn ", "SELECT", "FROM", "docker", "COPY", "RUN", "const ", "let ", "var ", "echo ", "sudo ", "git ", "npm ", "pip ", "cargo ", "#!", "if ", "for ", "while ", "case ", "bash", "sh -c", "apt", "yum", "brew", "print(", "console.", "```", "return ", "public ", "private ", "void ", "int ", "String ", "bool ", "float "]

verify_models()

def has_code_keywords(content):
    if any(kw in content for kw in CODE_KEYWORDS):
        return True
    if "```" in content:
        return True
    return False

def classify_task(query):
    q = query.lower()
    length = len(q)
    words = len(q.split())

    # Tiny: very short, simple fixes
    if length < 40 and not any(c in q for c in ["\n", "{"]) and words <= 8:
        return "tiny"
    # Architecture: design, pattern, system, multi-step
    if any(kw in q for kw in ["architecture", "design pattern", "system design", "multi-step",
                               "multi file", "project structure", "organize", "scalable",
                               "microservice", "deploy", "pipeline", "workflow"]):
        return "architecture"
    # Debug/refactor
    if any(kw in q for kw in ["debug", "fix", "bug", "error", "traceback", "refactor",
                               "optimize", "slow", "memory leak", "race condition",
                               "deadlock", "not working", "broken", "crash"]):
        return "refactor"
    # Complex: long, many requirements
    if length > 300 or words > 40 or any(c in q for c in ["\n\n", "1.", "2.", "3."]):
        return "complex"
    # Default: code gen
    return "code_gen"

def get_cascade(task_type):
    avail = MODELS
    q = avail.get("qwen")
    o = avail.get("ornith")
    qc = avail.get("qcloud")
    d = avail.get("ds")
    dp = avail.get("ds-paid")
    if dp and DEEPSEEK_KEY and budget_check():
        routes = {
            "tiny":        [m for m in [q] if m],
            "code_gen":    [m for m in [q, o, qc, d, dp] if m],
            "refactor":    [m for m in [q, o, qc, d, dp] if m],
            "architecture":[m for m in [qc, dp] if m],
            "complex":     [m for m in [q, o, qc, d, dp] if m],
        }
    else:
        routes = {
            "tiny":        [m for m in [q] if m],
            "code_gen":    [m for m in [q, o, qc, d] if m],
            "refactor":    [m for m in [q, o, qc, d] if m],
            "architecture":[m for m in [qc] if m],
            "complex":     [m for m in [q, o, qc, d] if m],
        }
    return routes.get(task_type, [m for m in [q, o, qc, d] if m])

def ask(model_cfg, messages, prev_error=""):
    for k in ["HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy"]:
        os.environ.pop(k, None)
    payload = {
        "model": model_cfg["name"],
        "messages": messages,
        "stream": False,
        "keep_alive": "15m",
        "options": {"temperature": 0, "num_predict": model_cfg["num_predict"]},
    }
    if model_cfg.get("think") is False:
        payload["think"] = False
    if prev_error:
        messages.append({"role": "system", "content": f"Previous model failed. Error: {prev_error[:500]}"})
    try:
        req = urllib.request.Request(
            f"{OLLAMA}/api/chat",
            data=json.dumps(payload).encode(),
            headers={"Content-Type": "application/json"},
        )
        resp = urllib.request.urlopen(req, timeout=60)
        data = json.loads(resp.read())
        content = data.get("message", {}).get("content", "")
        tok = data.get("eval_count", 0)
        duration = data.get("total_duration", 0) / 1e9
        return content, tok, duration
    except Exception as e:
        return f"Error: {e}", 0, 0

def ask_paid(compressed_query, original_query):
    if not DEEPSEEK_KEY:
        return "Error: No DeepSeek API key", 0, 0
    if not budget_check():
        return "Error: Budget exhausted", 0, 0
    for k in ["HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy"]:
        os.environ.pop(k, None)
    payload = {
        "model": "deepseek-v4-flash",
        "messages": [
            {"role": "system", "content": "You are a coding assistant. Provide working code only."},
            {"role": "user", "content": f"[RAG context: {compressed_query['snippet'][:200]}]\n\n{original_query}"},
        ],
        "stream": False,
        "max_tokens": 2048,
        "temperature": 0,
    }
    try:
        req = urllib.request.Request(
            DEEPSEEK_API,
            data=json.dumps(payload).encode(),
            headers={"Content-Type": "application/json", "Authorization": f"Bearer {DEEPSEEK_KEY}"},
        )
        resp = urllib.request.urlopen(req, timeout=60)
        data = json.loads(resp.read())
        content = data["choices"][0]["message"]["content"]
        usage = data.get("usage", {})
        in_tok = usage.get("prompt_tokens", 0)
        out_tok = usage.get("completion_tokens", 0)
        cost = budget_spend(in_tok, out_tok)
        return content, in_tok + out_tok, cost
    except Exception as e:
        return f"Error: {e}", 0, 0

def detect_repetition(content):
    """Detect repetitive/garbage patterns. Returns (has_issue, reason)."""
    lines = content.split('\n')
    # Check for repeated identical lines (>3x)
    line_counts = {}
    for l in lines:
        l = l.strip()
        if len(l) > 20:  # only meaningful lines
            line_counts[l] = line_counts.get(l, 0) + 1
    for text, count in line_counts.items():
        if count > 5:
            return True, f"line repeated {count}x"
    # Check for repeated code blocks (duplicate fn/struct/class definitions)
    blocks = re.findall(r'\b(?:fn |def |struct |class )\w+', content)
    block_counts = {}
    for b in blocks:
        block_counts[b] = block_counts.get(b, 0) + 1
    for b, c in block_counts.items():
        if c > 3:
            return True, f"definition '{b}' repeated {c}x"
    return False, "ok"

def heuristic_check(content, task_type):
    if not content or len(content) < 30:
        return False, "too short"
    if content.lower().startswith("error"):
        return False, "starts with error"
    # Repetition check
    has_repeat, reason = detect_repetition(content)
    if has_repeat:
        return False, f"repetitive garbage: {reason}"
    # Architecture/docs tasks don't need code keywords
    if task_type in ("architecture",):
        if len(content) < 1000:
            return False, f"too short for architecture ({len(content)} < 1000)"
        if len(content.split()) < 150:
            return False, f"too few words ({len(content.split())} < 150)"
        req_terms = ["cron", "data flow", "cascade", "tts", "opencode", "kiss",
                     "halt", "onedrive", "model", "instruction", "quality", "rag"]
        found = sum(1 for t in req_terms if t in content.lower())
        if found < 8:
            return False, f"too vague ({found}/{len(req_terms)} required terms)"
        if "|" not in content and "```" not in content:
            return False, "no tables or code blocks"
    else:
        if not has_code_keywords(content):
            return False, "no code keywords"
        # For code tasks, require at least one code block
        if task_type in ("code_gen", "refactor") and "```" not in content:
            return False, "no code blocks"
    return True, "ok"

def check_syntax(code, lang):
    lang = lang.lower().strip()
    if lang in ("py", "python"):
        try:
            compile(code.strip(), "<cascade>", "exec")
            return True, "ok"
        except SyntaxError as e:
            return False, f"python syntax error: {e}"
    if lang in ("js", "javascript", "mjs"):
        if not check_prog("node"):
            return True, "skip (node not found)"
        r = subprocess.run(["node", "--check", "-"], input=code.encode(), capture_output=True, timeout=10)
        if r.returncode != 0:
            lines = r.stderr.decode().strip().split("\n")
            err = next((l.strip() for l in lines if "SyntaxError" in l), lines[-1].strip() if lines else "parse error")
            return False, f"js syntax error: {err}"
        return True, "ok"
    if lang in ("ts", "typescript"):
        return True, "skip (ts check not available)"
    if lang in ("sh", "bash", "zsh", "shell"):
        if not check_prog("bash"):
            return True, "skip (bash not found)"
        r = subprocess.run(["bash", "-n", "/dev/stdin"], input=code.encode(), capture_output=True, timeout=10)
        if r.returncode != 0:
            err = r.stderr.decode().split("\n")[-2].strip() if r.stderr else "parse error"
            return False, f"bash syntax error: {err}"
        return True, "ok"
    return True, f"skip (no checker for {lang})"

def check_prog(name):
    return subprocess.run(["which", name], capture_output=True).returncode == 0

def get_code_blocks(code):
    blocks = re.findall(r"```(\w+)\n(.*?)```", code, re.DOTALL)
    if blocks:
        return blocks
    lines = code.split("\n")
    langs = {}
    js_lines = [l for l in lines if l.startswith(("const ", "let ", "var ", "function", "import ", "export ", "class "))]
    if js_lines:
        langs["js"] = js_lines
    py_lines = [l for l in lines if l.startswith(("def ", "class ", "import ", "from "))]
    if py_lines:
        langs["python"] = py_lines
    bash_lines = [l for l in lines if l.rstrip().startswith(("#!", "sudo", "docker", "git ", "npm ", "pip ", "cargo ", "echo ", "if ", "for ", "while ", "case "))]
    if bash_lines:
        langs["bash"] = bash_lines
    return [(lang, "\n".join(blocks)) for lang, blocks in langs.items()]

def execution_check(code):
    blocks = get_code_blocks(code)
    if not blocks:
        return True, "skip (no code blocks found)"
    for lang, block in blocks:
        # Skip syntax check for untagged blocks (ASCII art, data flow diagrams)
        if lang in ("text", "txt", "") or (not lang.isidentifier()):
            continue
        passed, reason = check_syntax(block, lang)
        if not passed:
            return False, reason
    return True, "ok"

def judge_query(content, query, task_type="code_gen"):
    judge_model = MODELS["ornith"]["name"] if "ornith" in MODELS else MODELS.get("cloud", MODELS["qwen"])["name"]
    try:
        if task_type == "architecture":
            prompt = f"""Evaluate this architecture document. Reply ONLY with YES or NO.

Query: {query}

Answer:
{content[:2500]}

Does the answer contain specific, detailed information about each requested topic? Or is it generic/vague filler text?

YES = at least 6 of these 12 required terms appear: cron, data flow, cascade, tts, opencode, kiss, halt, onedrive, model, instruction, quality, rag
NO = generic filler, boilerplate, or missing most required terms.

Reply with YES or NO and a one-line reason."""
        else:
            prompt = f"Query: {query}\n\nAnswer:\n{content[:2000]}\n\nDoes this provide working, correct code that directly solves the query? Answer YES or NO with reason."

        messages = [
            {"role": "system", "content": "You evaluate answers critically. Reply ONLY with YES or NO and a single-line reason."},
            {"role": "user", "content": prompt},
        ]
        payload = {
            "model": judge_model,
            "messages": messages,
            "stream": False,
            "options": {"temperature": 0, "num_predict": 100},
        }
        req = urllib.request.Request(f"{OLLAMA}/api/chat", data=json.dumps(payload).encode(), headers={"Content-Type": "application/json"})
        resp = json.loads(urllib.request.urlopen(req, timeout=60).read())
        verdict = resp.get("message", {}).get("content", "").strip().lower()
        if verdict.startswith("no"):
            return False, verdict[:80]
        return True, verdict[:80]
    except Exception as e:
        return True, f"judge failed ({e}) — accept"

def quality_gate(content, query="", task_type="code_gen"):
    passed, reason = heuristic_check(content, task_type)
    if not passed:
        return False, reason, content
    # Skip syntax check for non-code tasks
    if task_type != "tiny":
        passed, reason = execution_check(content)
        if not passed:
            return False, reason, content
    if query:
        passed, reason = judge_query(content, query, task_type)
        if not passed:
            return False, reason, content
    return True, "ok", content

def append_codes_md(query, model_name, code, chain, timing):
    now = time.strftime("%Y-%m-%d %H:%M")
    entry = f"""
## {now} | {query[:60]}
- **Model**: {model_name}
- **Chain**: {chain}
- **Time**: {timing:.1f}s
```python
{code[:500]}
```
"""
    target = CODES_MD if os.access(os.path.dirname(CODES_MD), os.W_OK) else CODES_MD_FALLBACK
    try:
        with open(target, "a") as f:
            f.write(entry)
        return target
    except OSError:
        return None

def fuche_ingest(collection):
    try:
        target = os.path.join(BASE_RAG, collection) if collection else BASE_RAG
        _ingest(target, collection)
    except Exception:
        pass

def search_commands(query):
    try:
        results = _search(query, "commands", top_k=6)
        if results:
            return "\n".join(snip for _, _, snip in results)
    except Exception:
        pass
    return ""

def cascade_answer(query):
    task = classify_task(query)
    cascade = get_cascade(task)
    print(f"  task={task} chain={len(cascade)} models", file=sys.stderr)

    cmd_ctx = search_commands(query)
    sys_content = "You are a coding assistant. Provide working code only."
    if cmd_ctx:
        sys_content += f"\n\nRelevant command examples:\n{cmd_ctx}"
        print(f"  → {len(cmd_ctx.split(chr(10)))} command snippets injected", file=sys.stderr)

    messages = [
        {"role": "system", "content": sys_content},
        {"role": "user", "content": query},
    ]
    prev_error = ""
    chain = []
    total_t0 = time.time()
    content = ""
    short_name = ""
    compressed = compress_query(query) if DEEPSEEK_KEY else (False, None)
    if compressed[0]:
        print(f"  RAG hit: kw={compressed[1]['kw']:.3f} src={compressed[1]['source']}", file=sys.stderr)

    for model_cfg in cascade:
        model_name = model_cfg["name"]
        short_name = model_name.split("/")[-1].replace(":Q4_K_M", "").replace(":latest", "")
        chain.append(short_name)
        print(f"  [{short_name}] trying...", file=sys.stderr)

        t0 = time.time()
        if model_cfg.get("paid"):
            hit, info = compressed
            if hit:
                content, tok, _ = ask_paid(info, query)
            else:
                print(f"  [{short_name}] no RAG hit, skipping paid tier", file=sys.stderr)
                prev_error = "No RAG compression available for paid tier"
                continue
        else:
            content, tok, _ = ask(model_cfg, messages.copy(), prev_error)
        elapsed = time.time() - t0
        print(f"  [{short_name}] {elapsed:.1f}s, {tok}tok", file=sys.stderr)

        if content.startswith("Error:"):
            prev_error = content
            continue

        passed, reason, _ = quality_gate(content, query, task)
        if passed:
            total = time.time() - total_t0
            print(f"  [{short_name}] ✅ passed ({reason})", file=sys.stderr)
            codes_path = append_codes_md(query, short_name, content, " → ".join(chain), total)
            if codes_path:
                print(f"  → saved to {codes_path}", file=sys.stderr)
            fuche_ingest("code-fixes")
            print(f"  → ingested into RAG (code-fixes)", file=sys.stderr)
            # write cascade status for UI - check actual Ollama loaded state
            import json
            loaded = get_loaded_ollama_models()
            status_models = [{"name": cfg["name"], "label": LABELS.get(key, key.capitalize()), "loaded": (cfg["name"].split(":")[0] in loaded)} for key, cfg in MODELS.items()]
            json.dump(status_models, open("/tmp/.cascade-status", "w"))
            return content, short_name, chain, total
        else:
            prev_error = f"Model output failed quality check: {reason}"
            print(f"  [{short_name}] ❌ {reason}", file=sys.stderr)

    total = time.time() - total_t0
    print(f"  All models failed — returning best attempt", file=sys.stderr)
    # write cascade status for UI - check actual Ollama loaded state
    import json
    loaded = get_loaded_ollama_models()
    status_models = [{"name": cfg["name"], "label": LABELS.get(key, key.capitalize()), "loaded": (cfg["name"].split(":")[0] in loaded)} for key, cfg in MODELS.items()]
    json.dump(status_models, open("/tmp/.cascade-status", "w"))
    return content, short_name, chain, total

if __name__ == "__main__":
    q = " ".join(sys.argv[1:]).strip()
    if q:
        ans, model, chain, elapsed = cascade_answer(q)
        print(ans)
        print(f"\n--- {model} ({' → '.join(chain)}) {elapsed:.1f}s ---", file=sys.stderr)
    else:
        print("Usage: python cascade.py 'your question'")
