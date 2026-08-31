import csv
import json
import os
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[1]
COMPANY = json.loads((ROOT / "config/company.json").read_text(encoding="utf-8"))
LEADS = ROOT / "data/social_leads.csv"

GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions"
DEFAULT_MODEL = "gemini-2.5-flash"
SECTORS = [
    "Petroleum products",
    "Chemicals",
    "Petrochemicals",
    "Steel",
    "Renewable energy / industrial raw materials",
]
COUNTRY = COMPANY.get("target_country", "China")
REGIONS = [
    "Guangdong (Guangzhou, Shenzhen, Foshan, Dongguan, Huizhou)",
    "Jiangsu (Nanjing, Suzhou, Wuxi, Changzhou, Nantong)",
    "Zhejiang (Ningbo, Hangzhou, Shaoxing, Jiaxing)",
    "Shandong (Qingdao, Dongying, Yantai, Weifang)",
    "Shanghai / Yangtze River Delta",
    "Tianjin / Bohai industrial belt",
    "Hebei (Tangshan, Cangzhou)",
    "Liaoning (Dalian, Shenyang, Yingkou)",
    "Fujian (Xiamen, Quanzhou, Fuzhou)",
    "Hubei (Wuhan, Yichang)",
]
INDUSTRIAL_ZONES = [
    "Shanghai Chemical Industry Park",
    "Ningbo Petrochemical Economic and Technological Development Zone",
    "Huizhou Daya Bay Petrochemical Industrial Zone",
    "Nanjing Jiangbei New Area",
    "Tianjin Nangang Industrial Zone",
    "Zhanjiang Economic and Technological Development Zone",
    "Dongying petrochemical clusters",
    "Cangzhou Lingang Economic and Technological Development Zone",
    "Ningbo Economic and Technological Development Zone",
    "Suzhou Industrial Park",
    "Guangzhou Nansha industrial clusters",
    "Foshan high-tech manufacturing clusters",
    "Tangshan Caofeidian Industrial Zone",
    "Dalian Changxing Island Economic and Technological Development Zone",
]


def existing_leads() -> list[dict[str, str]]:
    if not LEADS.exists():
        return []
    try:
        with LEADS.open(encoding="utf-8") as handle:
            return list(csv.DictReader(handle))
    except Exception:
        return []


def existing_urls_and_names() -> list[str]:
    out: list[str] = []
    for row in existing_leads():
        for key in ("url", "name"):
            value = str(row.get(key, "")).strip()
            if value:
                out.append(value)
    return out


def fallback_plan() -> dict[str, object]:
    rows = existing_leads()
    run_number = len({r.get("run_id", "") for r in rows if r.get("run_id")})
    sector = SECTORS[run_number % len(SECTORS)]
    region = REGIONS[run_number % len(REGIONS)]
    zone = INDUSTRIAL_ZONES[run_number % len(INDUSTRIAL_ZONES)]
    return {
        "country": COUNTRY,
        "sector": sector,
        "region": region,
        "industrial_zone": zone,
        "queries": [
            f"site:linkedin.com/company {COUNTRY} {region} {sector} procurement purchasing sourcing manufacturer importer",
            f"site:facebook.com {COUNTRY} {zone} {sector} company manufacturer distributor importer",
            f"{COUNTRY} {region} {sector} industrial buyer procurement factory importer company -jobs -careers -article -blog -directory",
        ],
    }


def plan() -> dict[str, object]:
    key = os.getenv("GEMINI_API_KEY", "").strip()
    model = os.getenv("GEMINI_MODEL", DEFAULT_MODEL).strip() or DEFAULT_MODEL
    used = existing_urls_and_names()
    used_text = "\n".join(used[-150:]) or "NONE"

    if not key:
        print("AI planner: GEMINI_API_KEY missing; using deterministic rotation fallback")
        return fallback_plan()

    prompt = f"""You are ROZHAN GLOBAL's B2B social-lead search planner.
Company: {COMPANY.get('brand', 'ROZHAN GLOBAL')}
Business: {COMPANY.get('positioning', 'international sourcing and cross-border procurement')}
TARGET COUNTRY: {COUNTRY} only.
CORE INDUSTRIES: {', '.join(SECTORS)}.
TARGET BUYERS: direct buyers, industrial consumers, importers, manufacturers, procurement/purchasing/sourcing teams, factories and raw-material consumers.

Design the NEXT hourly discovery batch. The batch must produce NEW companies/pages, not duplicates from prior runs.
Choose one primary industry and one geographic/industrial-cluster focus for this run.
Favor real operating companies/pages and buyer intent.
Use both platforms, but do NOT search for individual private people. For LinkedIn prefer company pages; for Facebook prefer public company/business Pages.
Use industrial parks, development zones, chemical parks, steel/manufacturing clusters and factory districts where relevant.
Never use jobs, recruitment, careers, articles, blogs, news, generic directories, lead-list vendors, marketplaces, courses, webinars or social posts as the lead itself.

Previously collected URLs/names to avoid:
{used_text}

Return ONLY valid JSON with this exact structure:
{{
  "country": "{COUNTRY}",
  "sector": "one of the core industries",
  "region": "specific region/city/industrial zone focus",
  "industrial_zone": "specific zone/cluster or empty string",
  "queries": ["query 1", "query 2", "query 3", "query 4"]
}}
Queries must be concise web searches. At least one must explicitly target LinkedIn company pages and one Facebook public business pages. Include strong negative terms where useful."""

    try:
        response = requests.post(
            GEMINI_URL,
            headers={
                "Authorization": f"Bearer {key}",
                "Content-Type": "application/json",
            },
            json={
                "model": model,
                "temperature": 0.25,
                "messages": [{"role": "user", "content": prompt}],
            },
            timeout=45,
        )
        response.raise_for_status()
        text = response.json()["choices"][0]["message"]["content"].strip()
        start, end = text.find("{"), text.rfind("}")
        if start >= 0 and end > start:
            result = json.loads(text[start : end + 1])
            queries = [str(q).strip() for q in result.get("queries", []) if str(q).strip()]
            if len(queries) >= 4:
                result["country"] = COUNTRY
                result["queries"] = queries[:4]
                print(
                    f"AI planner: sector={result.get('sector')} | region={result.get('region')} | "
                    f"zone={result.get('industrial_zone')} | queries={len(queries[:4])}"
                )
                return result
    except Exception as exc:
        print(f"AI planner failed: {exc}; using deterministic rotation fallback")

    return fallback_plan()
