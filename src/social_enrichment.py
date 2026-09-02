import csv
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .composio_client import ComposioClient

ROOT = Path(__file__).resolve().parents[1]
LEADS = ROOT / "data/social_leads.csv"
ACTIVITY = ROOT / "data/social_activity.csv"
LINKEDIN_ORGS = ROOT / "data/linkedin_connected_orgs.csv"
FIELDS = ["run_id", "platform", "slot", "target_name", "target_url", "tool", "status", "summary", "raw_json", "created_at"]
ORG_FIELDS = ["run_id", "organization_id", "name", "vanity_name", "website", "logo", "locations", "primary_organization_type", "raw_json", "created_at"]


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _save(row: dict[str, str]) -> None:
    exists = ACTIVITY.exists() and ACTIVITY.stat().st_size > 0
    with ACTIVITY.open("a", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDS)
        if not exists:
            writer.writeheader()
        writer.writerow({key: row.get(key, "") for key in FIELDS})


def _save_org(row: dict[str, str]) -> None:
    exists = LINKEDIN_ORGS.exists() and LINKEDIN_ORGS.stat().st_size > 0
    with LINKEDIN_ORGS.open("a", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=ORG_FIELDS)
        if not exists:
            writer.writeheader()
        writer.writerow({key: row.get(key, "") for key in ORG_FIELDS})


def _compact(value: Any, limit: int = 12000) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))[:limit]


def _summary(value: Any) -> str:
    if isinstance(value, dict):
        for key in ("message", "detail", "description", "text", "response", "error"):
            item = value.get(key)
            if isinstance(item, str) and item.strip():
                return item.strip()[:4000]
        return json.dumps(value, ensure_ascii=False)[:4000]
    return str(value)[:4000]


def _update_lead_context(run_id: str, target_url: str, social_notes: list[str]) -> None:
    if not LEADS.exists() or not social_notes:
        return
    with LEADS.open(encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        fields = reader.fieldnames or []
        rows = list(reader)
    if "snippet" not in fields:
        return
    note_text = " | ".join(n for n in social_notes if n)
    changed = False
    for row in rows:
        if row.get("run_id") == run_id and row.get("url") == target_url:
            existing = str(row.get("snippet", "")).strip()
            if "Composio social data:" not in existing:
                row["snippet"] = f"{existing} Composio social data: {note_text}".strip()
                changed = True
            elif note_text and note_text not in existing:
                row["snippet"] = f"{existing} | {note_text}"[:12000]
                changed = True
    if changed:
        with LEADS.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=fields)
            writer.writeheader()
            writer.writerows(rows)


def _run_tool(client: ComposioClient, tool: str, arguments: dict[str, Any]) -> tuple[str, str, str, dict[str, Any]]:
    result = client.execute_tool(tool, arguments=arguments, version="latest")
    data = result.get("data", result)
    return str(result.get("status", "unknown")), _summary(data), _compact(result), data if isinstance(data, dict) else {"result": data}


def _facebook_page_id(url: str) -> str:
    patterns = [
        r"/p/[^/]*-(\d{8,})/?",
        r"facebook\.com/(\d{8,})(?:/|\?|$)",
        r"m\.facebook\.com/(\d{8,})(?:/|\?|$)",
    ]
    for pattern in patterns:
        match = re.search(pattern, url, re.IGNORECASE)
        if match:
            return match.group(1)
    return ""


def _record(lead: dict[str, str], tool: str, status: str, summary: str, raw: str = "") -> None:
    _save({
        "run_id": lead.get("run_id", ""), "platform": lead.get("platform", ""), "slot": lead.get("slot", ""),
        "target_name": lead.get("name", ""), "target_url": lead.get("url", ""), "tool": tool,
        "status": status, "summary": summary, "raw_json": raw, "created_at": now_iso(),
    })


def _iter_org_candidates(value: Any):
    if isinstance(value, dict):
        keys = {str(k).lower() for k in value}
        looks_like_org = bool({"id", "name", "localizedname", "vanityname"} & keys)
        if looks_like_org:
            yield value
        for child in value.values():
            yield from _iter_org_candidates(child)
    elif isinstance(value, list):
        for item in value:
            yield from _iter_org_candidates(item)


def collect_connected_linkedin_organizations(run_id: str) -> int:
    """Collect organizations the connected LinkedIn member can access via Composio.

    This is deliberately separate from public LinkedIn discovery. LinkedIn's official
    organization APIs only expose richer organization data when the authenticated member
    has appropriate organization roles/permissions.
    """
    client = ComposioClient()
    lead = {"run_id": run_id, "platform": "linkedin", "slot": "connected_orgs", "name": "Connected LinkedIn organizations", "url": ""}
    tool = "LINKEDIN_GET_COMPANY_INFO"
    if not client.configured:
        _record(lead, tool, "not_configured", "Composio Project API key is not configured")
        return 0
    try:
        status, summary, raw, data = _run_tool(
            client,
            tool,
            {"role": "ADMINISTRATOR", "count": 100, "start": 0, "state": "APPROVED"},
        )
    except Exception as exc:
        _record(lead, tool, "exception", str(exc))
        return 0

    _record(lead, tool, status, summary, raw)
    if status != "success":
        print(f"LINKEDIN CONNECTED ORGS | status={status} | count=0")
        return 0

    seen: set[str] = set()
    count = 0
    for org in _iter_org_candidates(data):
        org_id = str(org.get("id") or org.get("organization_id") or "").strip()
        name = str(org.get("name") or org.get("localizedName") or org.get("localizedname") or "").strip()
        vanity = str(org.get("vanityName") or org.get("vanityname") or "").strip()
        key = org_id or vanity or name
        if not key or key in seen:
            continue
        seen.add(key)
        _save_org({
            "run_id": run_id,
            "organization_id": org_id,
            "name": name,
            "vanity_name": vanity,
            "website": str(org.get("localizedWebsite") or org.get("website") or ""),
            "logo": _compact(org.get("logoV2") or org.get("logo") or "", 2000),
            "locations": _compact(org.get("locations") or "", 4000),
            "primary_organization_type": str(org.get("primaryOrganizationType") or ""),
            "raw_json": _compact(org, 12000),
            "created_at": now_iso(),
        })
        count += 1

    print(f"LINKEDIN CONNECTED ORGS | status={status} | count={count}")
    return count


def collect_for_lead(lead: dict[str, str]) -> None:
    client = ComposioClient()
    platform = lead.get("platform", "")
    url = lead.get("url", "")
    social_notes: list[str] = []

    if not client.configured:
        _record(lead, "composio", "not_configured", "Composio Project API key is not configured")
        return

    tasks: list[tuple[str, dict[str, Any]]] = []
    if platform == "facebook":
        page_id = _facebook_page_id(url)
        if not page_id:
            _record(lead, "FACEBOOK_GET_PAGE_DETAILS", "fallback_required", "Target URL does not expose a numeric Facebook Page ID")
            _record(lead, "FACEBOOK_GET_PAGE_POSTS", "fallback_required", "Skipped because no numeric Facebook Page ID is available")
            print(f"SOCIAL ENRICHMENT | platform=facebook | slot={lead.get('slot')} | tool=FACEBOOK_GET_PAGE_DETAILS | status=fallback_required | target={url}")
            return
        tasks = [
            ("FACEBOOK_GET_PAGE_DETAILS", {"page_id": page_id, "fields": "id,name,about,category,description,followers_count,website,link,username,emails,phone,location,verification_status"}),
            ("FACEBOOK_GET_PAGE_POSTS", {"page_id": page_id, "limit": 10, "fields": "id,message,created_time,updated_time,permalink_url,attachments,from,shares,reactions.summary(true),comments.summary(true)"}),
        ]
    elif platform == "linkedin":
        tasks = [("LINKEDIN_GET_COMPANY_INFO", {"role": "ADMINISTRATOR", "count": 10, "start": 0, "state": "APPROVED"})]
    else:
        return

    for tool, arguments in tasks:
        try:
            status, summary, raw, _ = _run_tool(client, tool, arguments)
        except Exception as exc:
            status, summary, raw = "exception", str(exc), ""
        _record(lead, tool, status, summary, raw)
        if status == "success" and summary:
            social_notes.append(f"{tool}: {summary}")
        print(f"SOCIAL ENRICHMENT | platform={platform} | slot={lead.get('slot')} | tool={tool} | status={status} | target={url}")
    _update_lead_context(lead.get("run_id", ""), url, social_notes)


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
