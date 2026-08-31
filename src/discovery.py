import os
import re
from typing import Any
from urllib.parse import quote_plus, unquote

import requests

DEFAULT_QUERIES = {
    "linkedin": [
        "site:linkedin.com/company chemical distributor procurement petroleum products",
        "site:linkedin.com/company petrochemical buyer industrial chemicals steel procurement",
        "site:linkedin.com/company chemical trading company purchasing sourcing",
        "site:linkedin.com/company steel manufacturer procurement raw materials",
        "site:linkedin.com/company oil gas chemicals importer distributor",
    ],
    "facebook": [
        "site:facebook.com chemical distributor company",
        "site:facebook.com petrochemical trading company",
        "site:facebook.com industrial chemicals importer distributor",
        "site:facebook.com steel manufacturer procurement",
        "site:facebook.com oil gas chemicals distributor",
    ],
}


def _you_search(query: str) -> list[dict[str, str]]:
    key = os.getenv("YOU_API_KEY", "")
    if not key:
        return []
    url = os.getenv("YOU_SEARCH_URL", "https://ydc-index.io/v1/search")
    try:
        r = requests.post(
            url,
            headers={"X-API-Key": key, "Content-Type": "application/json", "Accept": "application/json"},
            json={"query": query, "count": 10, "safesearch": "moderate", "language": "en"},
            timeout=30,
        )
        r.raise_for_status()
        data: Any = r.json()
    except Exception as exc:
        print(f"You.com search failed: {exc}")
        return []

    results = data.get("results", {}) if isinstance(data, dict) else {}
    items = results.get("web", []) if isinstance(results, dict) else (results if isinstance(results, list) else [])
    out: list[dict[str, str]] = []
    for x in items:
        if not isinstance(x, dict):
            continue
        snippets = x.get("snippets", [])
        snippet = snippets[0] if isinstance(snippets, list) and snippets else x.get("description", "")
        out.append({
            "title": str(x.get("title", "")),
            "url": str(x.get("url", x.get("link", ""))),
            "snippet": str(snippet or ""),
        })
    return out


def _searx_search(query: str) -> list[dict[str, str]]:
    base = os.getenv("SEARXNG_URL", "").rstrip("/")
    if not base:
        return []
    try:
        r = requests.get(f"{base}/search", params={"q": query, "format": "json"}, timeout=30)
        r.raise_for_status()
        data = r.json()
    except Exception as exc:
        print(f"SearXNG search failed: {exc}")
        return []
    return [
        {"title": str(x.get("title", "")), "url": str(x.get("url", "")), "snippet": str(x.get("content", ""))}
        for x in data.get("results", []) if isinstance(x, dict)
    ]


def _duckduckgo_search(query: str) -> list[dict[str, str]]:
    try:
        r = requests.get(
            f"https://html.duckduckgo.com/html/?q={quote_plus(query)}",
            headers={"User-Agent": "Mozilla/5.0 ROZHAN-Lead-Discovery/1.0"}, timeout=30,
        )
        r.raise_for_status()
    except Exception as exc:
        print(f"DuckDuckGo search failed: {exc}")
        return []
    out: list[dict[str, str]] = []
    for m in re.finditer(r'<a[^>]+class="result__a"[^>]+href="([^"]+)"[^>]*>(.*?)</a>', r.text, re.I | re.S):
        href = unquote(m.group(1))
        uddg = re.search(r"uddg=([^&]+)", href)
        if uddg:
            href = unquote(uddg.group(1))
        title = re.sub(r"<.*?>", "", m.group(2)).strip()
        out.append({"title": title, "url": href, "snippet": ""})
    return out


def _clean(results: list[dict[str, str]], platform: str) -> list[dict[str, str]]:
    bad = ("/posts/", "/jobs/", "/events/", "/blog/", "/article/", "/search?", "/groups/")
    required = "linkedin.com/company/" if platform == "linkedin" else "facebook.com/"
    seen: set[str] = set()
    cleaned: list[dict[str, str]] = []
    for item in results:
        url = re.sub(r"#.*$", "", item.get("url", "").strip())
        low = url.lower()
        if not url or url in seen or required not in low or any(x in low for x in bad):
            continue
        seen.add(url)
        cleaned.append({**item, "url": url})
    return cleaned


def discover(platform: str, limit: int = 5) -> list[dict[str, str]]:
    collected: list[dict[str, str]] = []
    for query in DEFAULT_QUERIES[platform]:
        batch = _you_search(query) or _searx_search(query) or _duckduckgo_search(query)
        collected = _clean(collected + batch, platform)
        if len(collected) >= limit:
            break
    return collected[:limit]
