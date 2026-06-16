#!/usr/bin/env python3
import requests
import sys
import json
import time

OLLAMA = "http://localhost:11434/api/chat"

def ask(model, messages, temp=0.3, timeout=10):
    """Send request with timeout to avoid hanging."""
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
        else:
            return f"Error: HTTP {resp.status_code}"
    except requests.exceptions.Timeout:
        return "Error: Request timed out. Ollama may be busy or not responding."
    except requests.exceptions.ConnectionError:
        return "Error: Cannot connect to Ollama. Make sure it's running (ollama serve)."
    except Exception as e:
        return f"Error: {str(e)}"

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

if __name__ == "__main__":
    q = " ".join(sys.argv[1:])
    if not q:
        print("Usage: python main.py 'your question'")
        sys.exit(1)

    if is_code_question(q):
        print("💻 Code request → Qwen3:0.6b", file=sys.stderr)
        ans = ask("qwen3:0.6b", [{"role": "user", "content": q}], temp=0.2, timeout=15)
    else:
        print("🧠 General question → Hunyuan", file=sys.stderr)
        messages = [
            {"role": "system", "content": "You are a helpful assistant. Provide accurate, concise, factual answers. If you don't know, say so."},
            {"role": "user", "content": q}
        ]
        ans = ask("alibayram/hunyuan:0.5b", messages, temp=0.2, timeout=15)

    print(ans)
