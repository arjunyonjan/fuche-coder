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
URL_PATTERN = re.compile(r'^(https?://)?([a-zA-Z0-9-]+\.)+[a-zA-Z]{2,}(/[^\s]*)?$')


def extract_text_from_html(html):
    soup = BeautifulSoup(html, 'html.parser')
    for tag in soup(['script', 'style', 'nav', 'footer', 'header', 'aside']):
        tag.decompose()
    text = soup.get_text(separator=' ', strip=True)
    return re.sub(r'\s+', ' ', text).strip()


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
        text = extract_text_from_html(resp.text)
        if len(text) < 100:
            log.info(f"  ↳ {len(text)} chars (JS likely) — {url}")
        else:
            log.info(f"  ↳ {len(text)} chars — {url}")
        return text[:2000]
    except requests.Timeout:
        log.warning(f"  ↳ TIMEOUT — {url}")
    except requests.RequestException as e:
        log.warning(f"  ↳ {e} — {url}")
    except Exception as e:
        log.warning(f"  ↳ {e} — {url}")
    return ""


def fetch_page_text_js(url, timeout=15):
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        log.warning("  ↳ Playwright not installed — skipping JS render")
        return ""

    browsers = [
        ("chromium", {"args": ["--disable-http2"]}),
        ("firefox", {}),
    ]
    for browser_name, launch_kwargs in browsers:
        try:
            with sync_playwright() as p:
                browser = getattr(p, browser_name).launch(headless=True, **launch_kwargs)
                page = browser.new_page()
                page.goto(url, wait_until="domcontentloaded", timeout=timeout * 1000)
                import time
                time.sleep(2)
                html = page.content()
                browser.close()
            text = extract_text_from_html(html)
            log.info(f"  ↳ {len(text)} chars (JS render, {browser_name}) — {url}")
            return text[:2000]
        except Exception as e:
            log.info(f"  ↳ {browser_name} failed: {e}")
            continue
    return ""


def search_and_extract(query, max_results=3):
    # If query looks like a URL, try to fetch it directly first
    if URL_PATTERN.match(query.strip()):
        url = query.strip()
        if not url.startswith("http"):
            url = "https://" + url
        log.info(f"Direct URL fetch: {url}")
        content = fetch_page_text(url)
        if len(content) >= 100:
            return f"Content from {url}:\n\n{content}"
        # If too little content (JS SPA), try headless render
        log.info(f"  ↳ HTML too short — trying JS render")
        content_js = fetch_page_text_js(url)
        if content_js:
            return f"Content from {url} (JS rendered):\n\n{content_js}"
        return f"Content from {url}:\n\n{content or '(empty)'}"

    # Fall back to DDG search
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
