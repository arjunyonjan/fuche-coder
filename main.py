#!/usr/bin/env python3
import os
import sys
import requests

OLLAMA = "http://localhost:11434/api/chat"

CODE_MODEL = "qwen3:0.6b"
GEN_MODEL = "alibayram/hunyuan:0.5b"

SYSTEM_PROMPT = "You are a helpful assistant. Provide accurate, concise, factual answers. If you don't know, say so."

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

def chat():
    code_history = [{"role": "system", "content": SYSTEM_PROMPT}]
    gen_history = [{"role": "system", "content": SYSTEM_PROMPT}]

    print("⚡ Fuche AI Coder — interactive chat")
    print("   Commands: /exit  /clear  /model")
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
        ans = ask(model, history, temp=0.2)
        print(f"  {ans}\n")
        history.append({"role": "assistant", "content": ans})

def single_question(q):
    if is_code_question(q):
        print("💻 Code → Qwen3:0.6b", file=sys.stderr)
        ans = ask(CODE_MODEL, [{"role": "user", "content": q}], temp=0.2)
    else:
        print("🧠 General → Hunyuan", file=sys.stderr)
        ans = ask(GEN_MODEL, [
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
