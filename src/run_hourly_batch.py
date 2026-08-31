import csv
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path

from .discovery import discover
from .main import run_slot

ROOT = Path(__file__).resolve().parents[1]
LEADS = ROOT / "data/social_leads.csv"


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def append_lead(row: dict[str, str]) -> None:
    exists = LEADS.exists() and LEADS.stat().st_size > 0
    with LEADS.open("a", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=["run_id", "platform", "slot", "name", "url", "title", "snippet", "status", "created_at"])
        if not exists:
            writer.writeheader()
        writer.writerow(row)


def main() -> int:
    run_id = os.getenv("GITHUB_RUN_ID", str(uuid.uuid4()))
    total = 0
    for platform in ("facebook", "linkedin"):
        leads = discover(platform, limit=5)
        if len(leads) != 5:
            raise RuntimeError(f"Expected 5 discovered {platform} targets, got {len(leads)}. Configure YOU_API_KEY and/or SEARXNG_URL, then rerun.")
        for slot, lead in enumerate(leads, start=1):
            name = lead.get("title", "").strip() or lead.get("url", "").strip()
            append_lead({
                "run_id": run_id,
                "platform": platform,
                "slot": str(slot),
                "name": name,
                "url": lead.get("url", ""),
                "title": lead.get("title", ""),
                "snippet": lead.get("snippet", ""),
                "status": "discovered",
                "created_at": now_iso(),
            })
            run_slot(platform, slot, run_id, target=lead.get("url", ""), target_name=name)
            total += 1
    print(f"HOURLY BATCH COMPLETE | discovered_and_recorded={total} | facebook=5 | linkedin=5")
    if total != 10:
        raise RuntimeError(f"Expected exactly 10 records, got {total}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
