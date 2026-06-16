#!/usr/bin/env python3
import sys
import re
import requests
from bs4 import BeautifulSoup
from ddgs import DDGS

HEADERS = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}

def fetch_page_text(url, timeout=8):
    try:
        resp = requests.get(url, headers=HEADERS, timeout=timeout)
        if resp.status_code != 200:
            return ""
        soup = BeautifulSoup(resp.text, 'html.parser')
        for tag in soup(['script', 'style', 'nav', 'footer', 'header', 'aside']):
            tag.decompose()
        text = soup.get_text(separator=' ', strip=True)
        text = re.sub(r'\s+', ' ', text).strip()
        return text[:2000]
    except Exception:
        return ""

def search_and_extract(query, max_results=3):
    try:
        with DDGS() as ddgs:
            results = list(ddgs.text(query, max_results=max_results))
    except Exception as e:
        return f"Search failed: {e}"

    if not results:
        return f"Search results for: {query}\n\nNo results found."

    output = f"Search results for: {query}\n\n"
    for r in results:
        title = r.get("title", "").strip()
        href = r.get("href", "")
        snippet = r.get("body", "")
        output += f"Title: {title}\nURL: {href}\nSnippet: {snippet}\n"
        content = fetch_page_text(href)
        if content:
            output += f"Content: {content[:1000]}...\n"
        output += "\n"
    return output

if __name__ == "__main__":
    q = " ".join(sys.argv[1:])
    if not q:
        print("Usage: python crawler.py 'your question'")
        sys.exit(1)
    print(search_and_extract(q))
