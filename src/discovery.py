import os
from typing import Any

import requests


DEFAULT_QUERIES = {
    "linkedin": [
        "site:linkedin.com/company chemical distributor procurement manager petroleum products",
        "site:linkedin.com/company petrochemical buyer industrial chemicals steel procurement",
        "site:linkedin.com/company chemical trading company purchasing sourcing",
        "site:linkedin.com/company steel manufacturer procurement raw materials",
        "site:linkedin.com/company oil gas chemicals importer distributor",
    ],
    "facebook": [
        "chemical distributor company",
        "petrochemical trading company",
        "industrial chemicals importer distributor",
        "steel manufacturer procurement",
        "oil gas equipment chemicals distributor",
    ],
}


def _you_search(query: str) -> list[dict[str, str]]:
    key = os.getenv("YOU_API_KEY", "")
    if not key:
        return []
    url = os.getenv("YOU_SEARCH_URL", "https://api.you.com/v1/search")
    try:
        r = requests.get(
            url,
            headers={"X-API-Key": key, "Accept": "application/json"},
            params={"query": query},
            timeout=30,
        )
        r.raise_for_status()
        data: Any = r.json()
    except Exception as exc:
        print(f"You.com search failed: {exc}")
        return []

    results = data.get("results", []) if isinstance(data, dict) else []
    out: list[dict[str, str]] = []
    for item in results:
        if not isinstance(item, dict):
            continue
        out.append({
            "title": str(item.get("title", "")),
            "url": str(item.get("url", item.get("link", ""))),
            "snippet": str(item.get("description", item.get("snippet", ""))),
        })
    return out


def _searx_search(query: str) -> list[dict[str, str]]:
    base = os.getenv("SEARXNG_URL", "").rstrip("/")
    if not base:
        return []
    try:
        r = requests.get(
            f"{base}/search",
            params={"q": query, "format": "json"},
            timeout=30,
        )
        r.raise_for_status()
        data = r.json()
    except Exception as exc:
        print(f"SearXNG search failed: {exc}")
        return []
    out: list[dict[str, str]] = []
    for item in data.get("results", []):
        if isinstance(item, dict):
            out.append({
                "title": str(item.get("title", "")),
                "url": str(item.get("url", "")),
                "snippet": str(item.get("content", "")),
            })
    return out


def _clean(results: list[dict[str, str]], platform: str) -> list[dict[str, str]]:
    bad = ("/posts/", "/jobs/", "/events/", "/blog/", "/article/", "/search?")
    seen: set[str] = set()
    cleaned: list[dict[str, str]] = []
    for item in results:
        url = item.get("url", "").strip()
        if not url or url in seen or any(x in url.lower() for x in bad):
            continue
        if platform == "linkedin" and "linkedin.com" not in url.lower():
            continue
        seen.add(url)
        cleaned.append(item)
    return cleaned


def discover(platform: str, limit: int = 5) -> list[dict[str, str]]:
    collected: list[dict[str, str]] = []
    queries = DEFAULT_QUERIES[platform]
    for query in queries:
        batch = _you_search(query)
        if not batch:
            batch = _searx_search(query)
        collected.extend(batch)
        collected = _clean(collected, platform)
        if len(collected) >= limit:
            break

    return collected[:limit]
