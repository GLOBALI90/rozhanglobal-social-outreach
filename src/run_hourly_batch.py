import csv
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path

from .ai_planner import plan
from .discovery import discover
from .social_enrichment import collect_for_lead, collect_connected_linkedin_organizations

ROOT = Path(__file__).resolve().parents[1]
LEADS = ROOT / "data/social_leads.csv"
LEAD_FIELDS = [
    "run_id", "platform", "slot", "name", "url", "title", "snippet", "status",
    "country", "sector", "region", "industrial_zone", "planned_query", "created_at"
]


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def ensure_schema() -> None:
    if not LEADS.exists() or LEADS.stat().st_size == 0:
        return
    with LEADS.open(encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        old_fields = reader.fieldnames or []
        rows = list(reader)
    if old_fields == LEAD_FIELDS:
        return
    with LEADS.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=LEAD_FIELDS)
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in LEAD_FIELDS})


def append_lead(row: dict[str, str]) -> None:
    ensure_schema()
    exists = LEADS.exists() and LEADS.stat().st_size > 0
    with LEADS.open("a", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=LEAD_FIELDS)
        if not exists:
            writer.writeheader()
        writer.writerow({field: row.get(field, "") for field in LEAD_FIELDS})


def main() -> int:
    run_id = os.getenv("GITHUB_RUN_ID", str(uuid.uuid4()))
    total = 0
    planner = plan()
    print(
        "BATCH PLAN | country={} | sector={} | region={} | industrial_zone={}".format(
            planner.get("country", ""), planner.get("sector", ""), planner.get("region", ""), planner.get("industrial_zone", "")
        )
    )

    # Direct LinkedIn connection check/collection: retrieve organizations that the
    # connected member can access with the approved organization role. This does not
    # attempt to scrape or enumerate arbitrary public LinkedIn companies.
    connected_orgs = collect_connected_linkedin_organizations(run_id)
    print(f"LINKEDIN CONNECTED ORGANIZATION COLLECTION | count={connected_orgs}")

    for platform in ("facebook", "linkedin"):
        leads, _ = discover(platform, limit=5, planner=planner)
        if len(leads) != 5:
            raise RuntimeError(
                f"Expected 5 NEW discovered {platform} targets, got {len(leads)}. "
                "The AI planner/search layer must return five fresh targets."
            )
        queries = [str(q) for q in planner.get("queries", []) if str(q)]
        platform_hint = "LinkedIn company page" if platform == "linkedin" else "Facebook public business Page"
        for slot, lead in enumerate(leads, start=1):
            name = lead.get("title", "").strip() or lead.get("url", "").strip()
            row = {
                "run_id": run_id,
                "platform": platform,
                "slot": str(slot),
                "name": name,
                "url": lead.get("url", ""),
                "title": lead.get("title", ""),
                "snippet": lead.get("snippet", ""),
                "status": "discovered",
                "country": str(planner.get("country", "")),
                "sector": str(planner.get("sector", "")),
                "region": str(planner.get("region", "")),
                "industrial_zone": str(planner.get("industrial_zone", "")),
                "planned_query": next((q for q in queries if platform_hint.lower() in q.lower()), queries[0] if queries else ""),
                "created_at": now_iso(),
            }
            append_lead(row)
            total += 1

            collect_for_lead(row)

    print(
        f"HOURLY BATCH COMPLETE | discovered_and_recorded={total} | facebook=5 | linkedin=5 "
        f"| linkedin_connected_orgs={connected_orgs}"
        f" | country={planner.get('country')} | sector={planner.get('sector')}"
    )
    if total != 10:
        raise RuntimeError(f"Expected exactly 10 records, got {total}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
