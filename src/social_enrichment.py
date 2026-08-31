import csv
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .composio_client import ComposioClient

ROOT = Path(__file__).resolve().parents[1]
LEADS = ROOT / "data/social_leads.csv"
ACTIVITY = ROOT / "data/social_activity.csv"
FIELDS = [
    "run_id", "platform", "slot", "target_name", "target_url",
    "tool", "status", "summary", "raw_json", "created_at"
]


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _save(row: dict[str, str]) -> None:
    exists = ACTIVITY.exists() and ACTIVITY.stat().st_size > 0
    with ACTIVITY.open("a", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDS)
        if not exists:
            writer.writeheader()
        writer.writerow({key: row.get(key, "") for key in FIELDS})


def _compact(value: Any, limit: int = 12000) -> str:
    text = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    return text[:limit]


def _summary(value: Any) -> str:
    if isinstance(value, dict):
        for key in ("message", "detail", "description", "text", "response"):
            item = value.get(key)
            if isinstance(item, str) and item.strip():
                return item.strip()[:4000]
        return json.dumps(value, ensure_ascii=False)[:4000]
    return str(value)[:4000]


def _update_lead_context(run_id: str, target_url: str, social_notes: list[str]) -> None:
    if not LEADS.exists() or not social_notes:
        return
    with LEADS.open(encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
        fields = handle.name and (csv.DictReader(open(LEADS, encoding="utf-8")).fieldnames or [])
    if not fields or "snippet" not in fields:
        return
    changed = False
    note_text = " | ".join(n for n in social_notes if n)
    for row in rows:
        if row.get("run_id") == run_id and row.get("url") == target_url:
            existing = str(row.get("snippet", "")).strip()
            marker = "Composio social data: "
            if marker not in existing:
                row["snippet"] = f"{existing} {marker}{note_text}".strip()
                changed = True
            elif note_text and note_text not in existing:
                row["snippet"] = f"{existing} | {note_text}"[:12000]
                changed = True
    if not changed:
        return
    with LEADS.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def _run_tool(client: ComposioClient, tool: str, task: str) -> tuple[str, str, str]:
    result = client.execute_tool(tool, text=task, version="latest")
    status = str(result.get("status", "unknown"))
    data = result.get("data", result)
    return status, _summary(data), _compact(result)


def collect_for_lead(lead: dict[str, str]) -> None:
    client = ComposioClient()
    run_id = lead.get("run_id", "")
    platform = lead.get("platform", "")
    name = lead.get("name", "")
    url = lead.get("url", "")
    social_notes: list[str] = []

    if not client.configured:
        _save({
            "run_id": run_id, "platform": platform, "slot": lead.get("slot", ""),
            "target_name": name, "target_url": url, "tool": "composio",
            "status": "not_configured", "summary": "COMPOSIO_API_KEY/BASE_URL not configured",
            "raw_json": "", "created_at": now_iso(),
        })
        return

    tasks: list[tuple[str, str]] = []
    if platform == "facebook":
        tasks = [
            (
                "FACEBOOK_GET_PAGE_DETAILS",
                f'Using the connected Facebook Page account, retrieve public details for this business Page: {url}. The page name is "{name}". Return page name, category, description/about, website, location and other public business metadata available through the Page API. Read-only; do not modify anything.',
            ),
            (
                "FACEBOOK_GET_PAGE_POSTS",
                f'Using the connected Facebook Page account, retrieve recent public posts for the Page at {url}. The page name is "{name}". Return recent post text, timestamps and public engagement fields that are available. Read-only; do not create, like, comment, delete or modify anything.',
            ),
        ]
    elif platform == "linkedin":
        tasks = [
            (
                "LINKEDIN_GET_COMPANY_INFO",
                f'Using the connected LinkedIn account, retrieve public company information for the LinkedIn company page {url}. Company name: "{name}". Return company name, industry, description, website, location, company size and other public company fields available. Read-only; do not post, comment, connect or message.',
            ),
        ]

    for tool, task in tasks:
        try:
            status, summary, raw = _run_tool(client, tool, task)
        except Exception as exc:
            status, summary, raw = "exception", str(exc), ""
        _save({
            "run_id": run_id,
            "platform": platform,
            "slot": lead.get("slot", ""),
            "target_name": name,
            "target_url": url,
            "tool": tool,
            "status": status,
            "summary": summary,
            "raw_json": raw,
            "created_at": now_iso(),
        })
        if status == "success" and summary:
            social_notes.append(f"{tool}: {summary}")
        print(f"SOCIAL ENRICHMENT | platform={platform} | slot={lead.get('slot')} | tool={tool} | status={status} | target={url}")

    _update_lead_context(run_id, url, social_notes)


def enrich_run(run_id: str) -> int:
    if not LEADS.exists():
        return 0
    with LEADS.open(encoding="utf-8") as handle:
        leads = [row for row in csv.DictReader(handle) if row.get("run_id") == run_id]
    for lead in leads:
        collect_for_lead(lead)
    print(f"SOCIAL ENRICHMENT COMPLETE | run_id={run_id} | leads={len(leads)}")
    return len(leads)


if __name__ == "__main__":
    run_id = os.getenv("GITHUB_RUN_ID", "")
    raise SystemExit(0 if enrich_run(run_id) else 1)
