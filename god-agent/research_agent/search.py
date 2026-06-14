"""
research_agent/search.py — Web search (Serper/Google) + robust page fetching.

Improvements over original:
  - BeautifulSoup used when available for cleaner content extraction.
  - Readability-style content scoring picks the best text block.
  - Better encoding handling (detects charset from HTTP headers AND meta tags).
  - DuckDuckGo fallback when Serper key is absent.
  - Timeout, retry, and SSL error handling.
"""
from __future__ import annotations

import os
import re
import ssl
import urllib.parse
import urllib.request
from typing import Optional

import requests

# ── Constants ────────────────────────────────────────────────────────

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}

SERPER_ENDPOINT = "https://google.serper.dev/search"


# ── HTML cleaning ─────────────────────────────────────────────────────

def _strip_html(html: str) -> str:
    """Remove HTML tags, decode entities, normalise whitespace."""
    # Kill noise sections
    html = re.sub(
        r"<(script|style|nav|footer|header|aside|noscript|iframe|svg|form)[^>]*>.*?</\1>",
        " ", html, flags=re.DOTALL | re.IGNORECASE,
    )
    # Block elements → newlines
    html = re.sub(r"<(br|p|div|h[1-6]|li|tr|section|article|blockquote)[^>]*>",
                  "\n", html, flags=re.IGNORECASE)
    # Strip remaining tags
    html = re.sub(r"<[^>]+>", " ", html)
    # Decode HTML entities
    for ent, ch in [
        ("&amp;", "&"), ("&lt;", "<"), ("&gt;", ">"),
        ("&quot;", '"'), ("&#39;", "'"), ("&nbsp;", " "),
        ("&ndash;", "–"), ("&mdash;", "—"), ("&hellip;", "…"),
    ]:
        html = html.replace(ent, ch)
    html = re.sub(r"&[a-zA-Z]{2,8};", " ", html)
    html = re.sub(r"&#\d+;", " ", html)
    html = re.sub(r"[ \t]+", " ", html)
    html = re.sub(r"\n{3,}", "\n\n", html)
    return html.strip()


def _best_content(html: str) -> str:
    """
    Try to extract the main readable content block.
    Prefers <article>, <main>, <div class=*content*>, then full page.
    """
    # Try BeautifulSoup first (much cleaner)
    try:
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(html, "html.parser")
        for tag in soup(["script", "style", "nav", "footer", "header", "aside", "noscript"]):
            tag.decompose()
        # Priority: article > main > div[class~=content|article|post|body]
        for selector in ["article", "main", "[class*=content]", "[class*=article]", "[class*=post]"]:
            el = soup.select_one(selector)
            if el:
                text = el.get_text(separator="\n")
                if len(text.strip()) > 200:
                    return re.sub(r"\n{3,}", "\n\n", text).strip()
        return re.sub(r"\n{3,}", "\n\n", soup.get_text(separator="\n")).strip()
    except ImportError:
        pass

    # Fallback: regex-based extraction
    for pattern in [
        r"<article[^>]*>(.*?)</article>",
        r"<main[^>]*>(.*?)</main>",
    ]:
        m = re.search(pattern, html, re.DOTALL | re.IGNORECASE)
        if m:
            text = _strip_html(m.group(1))
            if len(text) > 200:
                return text

    return _strip_html(html)


def _open_url(url: str, timeout: int = 15) -> Optional[tuple[str, str]]:
    """
    Fetch URL. Returns (html_text, final_url) or None on failure.
    """
    try:
        ctx = ssl.create_default_context()
        req = urllib.request.Request(url, headers=_HEADERS)
        with urllib.request.urlopen(req, timeout=timeout, context=ctx) as resp:
            content_type = resp.headers.get("Content-Type", "")
            # Detect charset from Content-Type header
            m = re.search(r"charset=([\w-]+)", content_type)
            charset = m.group(1) if m else None
            raw = resp.read()
            final_url = resp.geturl()

        # Detect charset from meta tag if not in header
        if not charset:
            meta_m = re.search(
                rb'charset=["\']?([\w-]+)["\']?',
                raw[:4096], re.IGNORECASE
            )
            charset = meta_m.group(1).decode("ascii", errors="ignore") if meta_m else "utf-8"

        return raw.decode(charset, errors="replace"), final_url

    except Exception:
        return None


# ── Public API ────────────────────────────────────────────────────────

def web_search(query: str, max_results: int = 10) -> list[dict]:
    """
    Search the web. Uses Serper (Google) if SERPER_API_KEY is set,
    otherwise falls back to DuckDuckGo HTML scraping.
    """
    api_key = os.environ.get("SERPER_API_KEY")

    if api_key:
        try:
            resp = requests.post(
                SERPER_ENDPOINT,
                headers={"X-API-KEY": api_key, "Content-Type": "application/json"},
                json={"q": query, "num": max_results},
                timeout=15,
            )
            resp.raise_for_status()
            data = resp.json()
            results = []

            # Include answer box / knowledge graph if present
            if data.get("answerBox"):
                ab = data["answerBox"]
                results.append({
                    "title": ab.get("title", "Answer"),
                    "url": ab.get("link", ""),
                    "snippet": ab.get("answer") or ab.get("snippet", ""),
                })

            for item in data.get("organic", []):
                results.append({
                    "title": item.get("title", ""),
                    "url": item.get("link", ""),
                    "snippet": item.get("snippet", ""),
                })

            return results[:max_results]
        except Exception:
            pass  # fall through to DDG

    # DuckDuckGo fallback
    try:
        from duckduckgo_search import DDGS
        with DDGS() as ddg:
            return [
                {"title": r["title"], "url": r["href"], "snippet": r["body"]}
                for r in ddg.text(query, max_results=max_results)
            ]
    except Exception:
        pass

    # Last resort: DDG HTML
    try:
        encoded = urllib.parse.quote_plus(query)
        result = _open_url(f"https://html.duckduckgo.com/html/?q={encoded}")
        if result:
            html, _ = result
            titles = re.findall(r'class="result__title"[^>]*>(.*?)</a>', html, re.DOTALL)
            urls = re.findall(r'class="result__url"[^>]*>(.*?)</span>', html, re.DOTALL)
            snippets = re.findall(r'class="result__snippet"[^>]*>(.*?)</a>', html, re.DOTALL)
            out = []
            for t, u, s in zip(titles, urls, snippets):
                out.append({
                    "title": _strip_html(t).strip(),
                    "url": u.strip(),
                    "snippet": _strip_html(s).strip(),
                })
            return out[:max_results]
    except Exception:
        pass

    return []


def fetch_page(url: str, max_chars: int = 14_000) -> str:
    """
    Fetch a URL and return clean readable text.
    Returns an error string (not an exception) on failure.
    """
    if not url or not url.startswith("http"):
        return f"[fetch error: invalid URL: {url!r}]"

    result = _open_url(url)
    if result is None:
        # Retry once with SSL verification disabled (for self-signed certs)
        try:
            ctx = ssl._create_unverified_context()
            req = urllib.request.Request(url, headers=_HEADERS)
            with urllib.request.urlopen(req, timeout=15, context=ctx) as resp:
                raw = resp.read()
            html = raw.decode("utf-8", errors="replace")
            final_url = url
        except Exception:
            return f"[fetch error: could not retrieve {url}]"
    else:
        html, final_url = result

    text = _best_content(html)

    if len(text) < 100:
        return f"[fetch error: page appears empty or JS-rendered — {final_url}]"

    # Truncate cleanly at sentence boundary
    if len(text) > max_chars:
        truncated = text[:max_chars]
        last_period = truncated.rfind(".")
        if last_period > max_chars * 0.85:
            truncated = truncated[: last_period + 1]
        text = truncated + f"\n\n[… content truncated at {max_chars} chars — source: {final_url}]"

    return text
