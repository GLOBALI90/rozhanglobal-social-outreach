import csv
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
DATA.mkdir(exist_ok=True)
ACTIONS = DATA / "social_actions.csv"

FIELDS = ["run_id", "platform", "slot", "action", "target", "message", "status", "result", "created_at"]


def append_action(row: dict[str, str]) -> None:
    exists = ACTIONS.exists()
    with ACTIONS.open("a", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDS)
        if not exists:
            writer.writeheader()
        writer.writerow({field: row.get(field, "") for field in FIELDS})


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()
