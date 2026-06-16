#!/usr/bin/env python3
import sys
import requests
from bs4 import BeautifulSoup
import re

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

def search_and_extract(query):
    search_url = f"https://html.duckduckgo.com/html/?q={query.replace(' ', '+')}"

    try:
        resp = requests.get(search_url, headers=HEADERS, timeout=10)
        soup = BeautifulSoup(resp.text, 'html.parser')
        results = soup.find_all('a', class_='result__a')[:3]

        output = f"Search results for: {query}\n\n"
        for r in results:
            title = r.text.strip()
            href = r.get('href', '')
            output += f"Title: {title}\nURL: {href}\n"
            content = fetch_page_text(href)
            if content:
                output += f"Content: {content[:1000]}...\n"
            output += "\n"
        return output
    except Exception as e:
        return f"Search failed: {e}"

if __name__ == "__main__":
    q = " ".join(sys.argv[1:])
    if not q:
        print("Usage: python crawler.py 'your question'")
        sys.exit(1)
    print(search_and_extract(q))
