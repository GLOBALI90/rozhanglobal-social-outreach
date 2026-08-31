import csv
import json
import os
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[1]
COMPANY = json.loads((ROOT / "config/company.json").read_text(encoding="utf-8"))
LEADS = ROOT / "data/social_leads.csv"

GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions"
GEMINI_DEFAULT_MODEL = "gemini-3.6-flash"
CLOUDFLARE_URL_TEMPLATE = "https://api.cloudflare.com/client/v4/accounts/{account_id}/ai/run/{model}"
CLOUDFLARE_DEFAULT_MODEL = "@cf/zai-org/glm-4.7-flash"

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
        "provider": "deterministic-fallback",
        "country": COUNTRY,
        "sector": sector,
        "region": region,
        "industrial_zone": zone,
        "queries": [
            f"site:linkedin.com/company {COUNTRY} {region} {sector} procurement purchasing sourcing manufacturer importer -jobs -careers -recruitment",
            f"site:linkedin.com/company {COUNTRY} {zone} {sector} industrial buyer factory procurement -jobs -careers",
            f"site:facebook.com {COUNTRY} {zone} {sector} company manufacturer distributor importer -jobs -careers",
            f"site:facebook.com {COUNTRY} {region} {sector} industrial company procurement sourcing factory -jobs -groups",
        ],
    }


def build_prompt(used_text: str) -> str:
    return f"""You are ROZHAN GLOBAL's B2B social-lead search planner.
Company: {COMPANY.get('brand', 'ROZHAN GLOBAL')}
Business positioning: {COMPANY.get('positioning', 'international sourcing and cross-border procurement')}
TARGET COUNTRY: {COUNTRY} only.
CORE INDUSTRIES: {', '.join(SECTORS)}.
TARGET BUYERS: direct buyers, industrial consumers, importers, manufacturers, procurement/purchasing/sourcing teams, factories and raw-material consumers.

Design the NEXT hourly discovery batch. It must produce NEW companies/pages and avoid every URL/name already collected.
Choose one primary industry and one geographic/industrial-cluster focus for this run. Rotate the focus so repeated hourly runs explore different Chinese regions, cities and industrial clusters.
Use both platforms, but do NOT search for private individuals. For LinkedIn prefer public company pages. For Facebook prefer public company/business Pages.
Use industrial parks, development zones, chemical parks, steel/manufacturing clusters and factory districts where relevant.
Never use jobs, recruitment, careers, articles, blogs, news, generic directories, lead-list vendors, marketplaces, courses, webinars, social posts or individual profiles as the lead itself.
Prefer real operating companies with buyer/procurement relevance.

Previously collected URLs/names to avoid:
{used_text}

Return ONLY valid JSON with this exact structure:
{{
  "country": "{COUNTRY}",
  "sector": "one of the core industries",
  "region": "specific region/city/industrial cluster focus",
  "industrial_zone": "specific zone/cluster or empty string",
  "queries": [
    "LinkedIn company query 1",
    "LinkedIn company query 2",
    "Facebook public business Page query 1",
    "Facebook public business Page query 2"
  ]
}}
The four queries MUST be exactly two LinkedIn queries containing `site:linkedin.com/company` and two Facebook queries containing `site:facebook.com`. Never put a LinkedIn site filter in a Facebook query or vice versa. Include strong negative terms where useful."""


def parse_plan(text: str, provider: str) -> dict[str, object] | None:
    text = (text or "").strip()
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end <= start:
        return None
    try:
        result = json.loads(text[start : end + 1])
    except Exception:
        return None
    queries = [str(q).strip() for q in result.get("queries", []) if str(q).strip()]
    linkedin = [q for q in queries if "site:linkedin.com/company" in q.lower()]
    facebook = [q for q in queries if "site:facebook.com" in q.lower()]
    if len(queries) < 4 or len(linkedin) < 2 or len(facebook) < 2:
        return None
    result["provider"] = provider
    result["country"] = COUNTRY
    result["queries"] = (linkedin[:2] + facebook[:2])
    return result


def call_gemini(prompt: str) -> dict[str, object] | None:
    key = os.getenv("GEMINI_API_KEY", "").strip()
    if not key:
        print("AI planner: Gemini key missing")
        return None
    model = os.getenv("GEMINI_MODEL", GEMINI_DEFAULT_MODEL).strip() or GEMINI_DEFAULT_MODEL
    try:
        response = requests.post(
            GEMINI_URL,
            headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
            json={
                "model": model,
                "temperature": 0.2,
                "messages": [{"role": "user", "content": prompt}],
            },
            timeout=45,
        )
        response.raise_for_status()
        text = response.json()["choices"][0]["message"]["content"]
        result = parse_plan(text, f"gemini:{model}")
        if result:
            print(f"AI planner: Gemini primary succeeded | model={model}")
        return result
    except Exception as exc:
        print(f"AI planner: Gemini primary failed: {exc}")
        return None


def call_cloudflare(prompt: str) -> dict[str, object] | None:
    token = os.getenv("CLOUDFLARE_API_TOKEN", "").strip()
    account_id = os.getenv("CLOUDFLARE_ACCOUNT_ID", "").strip()
    if not token or not account_id:
        print("AI planner: Cloudflare fallback credentials missing")
        return None
    model = os.getenv("CLOUDFLARE_AI_MODEL", CLOUDFLARE_DEFAULT_MODEL).strip() or CLOUDFLARE_DEFAULT_MODEL
    url = CLOUDFLARE_URL_TEMPLATE.format(account_id=account_id, model=model)
    try:
        response = requests.post(
            url,
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
            json={"prompt": prompt, "max_tokens": 1200, "temperature": 0.2},
            timeout=45,
        )
        response.raise_for_status()
        payload = response.json().get("result", {})
        text = payload.get("response", "") if isinstance(payload, dict) else str(payload)
        result = parse_plan(text, f"cloudflare:{model}")
        if result:
            print(f"AI planner: Cloudflare fallback succeeded | model={model}")
        return result
    except Exception as exc:
        print(f"AI planner: Cloudflare fallback failed: {exc}")
        return None


def plan() -> dict[str, object]:
    used = existing_urls_and_names()
    used_text = "\n".join(used[-200:]) or "NONE"
    prompt = build_prompt(used_text)

    result = call_gemini(prompt)
    if result:
        return result

    result = call_cloudflare(prompt)
    if result:
        return result

    print("AI planner: both AI providers unavailable; using deterministic rotation fallback")
    return fallback_plan()
