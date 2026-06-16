#!/usr/bin/env python3
import requests
import sys
import time

OLLAMA = "http://localhost:11434/api/generate"

def ask(model, prompt):
    r = requests.post(OLLAMA, json={
        "model": model,
        "prompt": prompt,
        "stream": False,
        "options": {"temperature": 0.3}
    })
    return r.json().get("response", "")

def quality_check(answer, question):
    if not answer or answer.startswith("Search failed"):
        return 0.0
    words = set(question.lower().split())
    found = sum(1 for w in words if w in answer.lower() and len(w) > 2)
    keyword_ratio = found / max(len(words), 1)
    length_score = min(len(answer) / 500, 1.0)
    return min(keyword_ratio * 0.6 + length_score * 0.4, 1.0)

def refine_keywords(original, current, quality):
    prompt = f"Original: {original}\nCurrent keywords: {current}\nQuality: {quality}\nGenerate better search keywords (only keywords):"
    return ask("alibayram/hunyuan:0.5b", prompt)

def search(query):
    from crawler import search_and_extract
    try:
        return search_and_extract(query)
    except Exception as e:
        return f"Search failed: {e}"

def self_heal(question, max_loops=3):
    keywords = question
    for loop in range(1, max_loops + 1):
        print(f"Loop {loop}: Searching with '{keywords}'")
        result = search(keywords)
        quality = quality_check(result, question)
        print(f"Quality: {quality:.2f}")
        
        if quality >= 0.7:
            print("✅ Good result")
            return result
        
        if loop < max_loops:
            keywords = refine_keywords(question, keywords, quality)
            print(f"Refined keywords: {keywords}")
            time.sleep(1)
    
    print("⚠️ Max loops reached, returning best result")
    return result

if __name__ == "__main__":
    q = " ".join(sys.argv[1:])
    if not q:
        print("Usage: python loop.py 'your question'")
        sys.exit(1)
    print(self_heal(q))
