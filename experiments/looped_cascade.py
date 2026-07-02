#!/usr/bin/env python3
"""EXPERIMENT: Looped Transformer Cascade — single model, N internal loops.
   Does NOT modify cascade.py. Run: python3 experiments/looped_cascade.py"""

import sys, os, json, time, urllib.request
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from cascade import classify_task, heuristic_check, OLLAMA, MODELS

OLLAMA = "http://localhost:11434"

def ask_looped(model_cfg, query, loops=1):
    for k in ["HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy"]:
        os.environ.pop(k, None)
    msgs = [{"role": "user", "content": query}]
    content, output = query, ""
    for i in range(loops):
        payload = {
            "model": model_cfg["name"],
            "messages": msgs,
            "stream": False,
            "keep_alive": "15m",
            "options": {"temperature": 0, "num_predict": model_cfg["num_predict"]},
        }
        if model_cfg.get("think") is False:
            payload["think"] = False
        try:
            req = urllib.request.Request(
                f"{OLLAMA}/api/chat",
                data=json.dumps(payload).encode(),
                headers={"Content-Type": "application/json"},
            )
            resp = urllib.request.urlopen(req, timeout=180)
            data = json.loads(resp.read())
            output = data.get("message", {}).get("content", "")
            tok = data.get("eval_count", 0)
            dur = data.get("total_duration", 0) / 1e9
            print(f"  loop {i+1}/{loops}: {tok} tok, {dur:.2f}s")
            msgs.append({"role": "assistant", "content": output})
            msgs.append({"role": "user", "content": "Review and improve your previous answer. Add details, fix errors, be more precise."})
        except Exception as e:
            print(f"  loop {i+1}/{loops}: ERROR {e}")
            break
    return output

def compute_dial(query):
    cls = classify_task(query)
    dial = {"tiny": 1, "code_gen": 3, "refactor": 3, "architecture": 5, "complex": 8}
    return dial.get(cls, 3), cls

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python3 experiments/looped_cascade.py <query> [loops]")
        sys.exit(1)
    query = sys.argv[1]
    loops = int(sys.argv[2]) if len(sys.argv) > 2 else None
    if loops is None:
        loops, cls = compute_dial(query)
        print(f"class: {cls}, auto-loops: {loops}")
    else:
        print(f"manual loops: {loops}")
    model = MODELS["qwen"]
    print(f"model: {model['name']}")
    t0 = time.time()
    out = ask_looped(model, query, loops)
    print(f"\ntotal: {time.time()-t0:.1f}s")
    print(f"---\n{out[:300]}...")
