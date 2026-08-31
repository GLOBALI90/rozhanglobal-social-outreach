import argparse
import json
import os
import uuid
from pathlib import Path

from .composio_client import ComposioClient
from .state import append_action, now_iso

ROOT = Path(__file__).resolve().parents[1]
SOCIAL = json.loads((ROOT / "config/social.json").read_text(encoding="utf-8"))


def build_plan(platform: str, slot: int) -> list[dict[str, str]]:
    actions = SOCIAL["actions"][platform]
    if "find_target" not in actions:
        return []
    # One record belongs to each slot. Five Facebook slots + five LinkedIn slots
    # therefore produce exactly 10 records per hourly batch.
    return [{"action": "find_target", "target": f"{platform}-slot-{slot}", "message": ""}]


def run_slot(platform: str, slot: int, run_id: str | None = None) -> dict[str, str]:
    run_id = run_id or os.getenv("GITHUB_RUN_ID", str(uuid.uuid4()))
    live_mode = os.getenv("LIVE_MODE", str(SOCIAL.get("live_mode", False))).lower() == "true"
    client = ComposioClient()

    print(f"ROZHAN Social Outreach | platform={platform} | slot={slot} | live_mode={live_mode}")
    items = build_plan(platform, slot)
    for item in items:
        result = client.execute(
            action=f"{platform}.{item['action']}",
            payload={"target": item["target"], "message": item["message"]},
            live_mode=live_mode,
        )
        append_action({
            "run_id": run_id,
            "platform": platform,
            "slot": str(slot),
            "action": item["action"],
            "target": item["target"],
            "message": item["message"],
            "status": result.get("status", "unknown"),
            "result": json.dumps(result, ensure_ascii=False),
            "created_at": now_iso(),
        })
        print(json.dumps(result, ensure_ascii=False))
        return result
    return {"status": "no_action"}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--platform", choices=["linkedin", "facebook"], required=True)
    parser.add_argument("--slot", type=int, choices=range(1, 6), required=True)
    parser.add_argument("--run-id", default=None)
    args = parser.parse_args()
    run_slot(args.platform, args.slot, args.run_id)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
