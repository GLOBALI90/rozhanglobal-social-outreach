import csv
import os
import re
from pathlib import Path
from typing import Any
from urllib.parse import quote_plus, unquote

import requests

from .ai_planner import plan

ROOT = Path(__file__).resolve().parents[1]
LEADS = ROOT / "data/social_leads.csv"
DEFAULT_YOU_URL = "https://ydc-index.io/v1/search"
HEADERS = {"User-Agent": "Mozilla/5.0 ROZHAN-Social-Lead-Discovery/1.0"}


def _history() -> set[str]:
    values: set[str] = set()
    if not LEADS.exists():
        return values
    try:
        with LEADS.open(encoding="utf-8") as handle:
            for row in csv.DictReader(handle):
                for key in ("url", "name", "title"):
                    value = str(row.get(key, "")).strip().lower().rstrip("/")
                    if value:
                        values.add(value)
    except Exception as exc:
        print(f"Lead history read failed: {exc}")
    return values


def _you_search(query: str) -> list[dict[str, str]]:
    key = os.getenv("YOU_API_KEY", "").strip()
    if not key:
        return []
    url = os.getenv("YOU_SEARCH_URL", "").strip() or DEFAULT_YOU_URL
    try:
        response = requests.post(
            url,
            headers={"X-API-Key": key, "Accept": "application/json", "Content-Type": "application/json"},
            json={"query": query, "count": 15},
            timeout=30,
        )
        response.raise_for_status()
        data: Any = response.json()
    except Exception as exc:
        print(f"You.com search failed: {exc}")
        return []

    results = data.get("results", {}) if isinstance(data, dict) else {}
    web = results.get("web", []) if isinstance(results, dict) else results
    if not isinstance(web, list):
        return []
    out: list[dict[str, str]] = []
    for item in web:
        if not isinstance(item, dict):
            continue
        snippets = item.get("snippets", [])
        snippet = snippets[0] if isinstance(snippets, list) and snippets else item.get("description", item.get("snippet", ""))
        out.append({
            "title": str(item.get("title", "")).strip(),
            "url": str(item.get("url", item.get("link", ""))).strip(),
            "snippet": str(snippet or "").strip(),
        })
    return out


def _searx_search(query: str) -> list[dict[str, str]]:
    base = os.getenv("SEARXNG_URL", "").strip().rstrip("/")
    if not base or "your-searx-instance.example" in base:
        return []
    try:
        response = requests.get(f"{base}/search", params={"q": query, "format": "json"}, headers=HEADERS, timeout=30)
        response.raise_for_status()
        data = response.json()
    except Exception as exc:
        print(f"SearXNG search failed: {exc}")
        return []
    return [
        {"title": str(x.get("title", "")), "url": str(x.get("url", "")), "snippet": str(x.get("content", ""))}
        for x in data.get("results", []) if isinstance(x, dict)
    ]


def _duckduckgo_search(query: str) -> list[dict[str, str]]:
    try:
        response = requests.get(
            f"https://html.duckduckgo.com/html/?q={quote_plus(query)}",
            headers=HEADERS,
            timeout=30,
        )
        response.raise_for_status()
    except Exception as exc:
        print(f"DuckDuckGo search failed: {exc}")
        return []
    out: list[dict[str, str]] = []
    for match in re.finditer(r'<a[^>]+class="result__a"[^>]+href="([^"]+)"[^>]*>(.*?)</a>', response.text, re.I | re.S):
        href = unquote(match.group(1))
        uddg = re.search(r"uddg=([^&]+)", href)
        if uddg:
            href = unquote(uddg.group(1))
        title = re.sub(r"<.*?>", "", match.group(2)).strip()
        out.append({"title": title, "url": href, "snippet": ""})
    return out


def _clean(results: list[dict[str, str]], platform: str, history: set[str]) -> list[dict[str, str]]:
    required = "linkedin.com/company/" if platform == "linkedin" else "facebook.com/"
    bad_fragments = ("/posts/", "/post/", "/jobs/", "/careers/", "/events/", "/blog/", "/article/", "/search?", "/groups/", "/marketplace/", "/reel/", "/videos/", "/stories/")
    cleaned: list[dict[str, str]] = []
    seen: set[str] = set()
    for item in results:
        url = re.sub(r"#.*$", "", item.get("url", "").strip())
        low = url.lower().rstrip("/")
        title = item.get("title", "").strip()
        title_key = title.lower().rstrip("/")
        if not url or required not in low or any(x in low for x in bad_fragments):
            continue
        if low in history or title_key in history or low in seen:
            continue
        seen.add(low)
        cleaned.append({"title": title, "url": url, "snippet": item.get("snippet", "").strip()})
    return cleaned


def discover(platform: str, limit: int = 5, *, planner: dict[str, object] | None = None) -> tuple[list[dict[str, str]], dict[str, object]]:
    if platform not in {"facebook", "linkedin"}:
        raise ValueError(f"Unsupported platform: {platform}")
    planner = planner or plan()
    history = _history()
    queries = [str(q).strip() for q in planner.get("queries", []) if str(q).strip()]
    collected: list[dict[str, str]] = []

    for query in queries:
        results = _you_search(query)
        provider = "You.com"
        if not results:
            results = _searx_search(query)
            provider = "SearXNG"
        if not results:
            results = _duckduckgo_search(query)
            provider = "DuckDuckGo"
        candidates = _clean(results, platform, history)
        collected = _clean(collected + candidates, platform, history)
        print(f"Discovery | platform={platform} | provider={provider} | new_candidates={len(candidates)} | query={query}")
        if len(collected) >= limit:
            break

    return collected[:limit], planner
