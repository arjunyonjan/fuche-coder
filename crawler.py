#!/usr/bin/env python3
import logging
import re
import sys
import urllib3
import requests
from bs4 import BeautifulSoup
from ddgs import DDGS
from requests.exceptions import SSLError

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

logging.basicConfig(level=logging.INFO, format="%(message)s", stream=sys.stderr)
log = logging.getLogger(__name__)

HEADERS = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}

def fetch_page_text(url, timeout=8):
    try:
        try:
            resp = requests.get(url, headers=HEADERS, timeout=timeout, verify=True)
        except SSLError:
            log.info(f"  ↳ SSL error — retrying without verification")
            resp = requests.get(url, headers=HEADERS, timeout=timeout, verify=False)
        if resp.status_code != 200:
            log.warning(f"  ↳ HTTP {resp.status_code} — {url}")
            return ""
        soup = BeautifulSoup(resp.text, 'html.parser')
        for tag in soup(['script', 'style', 'nav', 'footer', 'header', 'aside']):
            tag.decompose()
        text = soup.get_text(separator=' ', strip=True)
        text = re.sub(r'\s+', ' ', text).strip()
        log.info(f"  ↳ {len(text)} chars — {url}")
        return text[:2000]
    except requests.Timeout:
        log.warning(f"  ↳ TIMEOUT — {url}")
    except requests.RequestException as e:
        log.warning(f"  ↳ {e} — {url}")
    except Exception as e:
        log.warning(f"  ↳ {e} — {url}")
    return ""

def search_and_extract(query, max_results=3):
    try:
        with DDGS() as ddgs:
            results = list(ddgs.text(query, max_results=max_results))
    except Exception as e:
        log.error(f"Search failed: {e}")
        return f"Search failed: {e}"

    if not results:
        log.info("No search results found.")
        return f"Search results for: {query}\n\nNo results found."

    output = f"Search results for: {query}\n\n"
    ok = 0
    for r in results:
        title = r.get("title", "").strip()
        href = r.get("href", "")
        snippet = r.get("body", "")
        output += f"Title: {title}\nURL: {href}\nSnippet: {snippet}\n"
        content = fetch_page_text(href)
        if content:
            ok += 1
            output += f"Content: {content[:1000]}...\n"
        output += "\n"
    log.info(f"  ✓ {ok}/{len(results)} pages fetched")
    return output

if __name__ == "__main__":
    q = " ".join(sys.argv[1:])
    if not q:
        print("Usage: python crawler.py 'your question'")
        sys.exit(1)
    print(search_and_extract(q))
