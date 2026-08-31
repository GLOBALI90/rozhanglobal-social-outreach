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
    # Initial MVP is intentionally non-destructive: plan only one discovery
    # action per run until concrete Composio mappings and target strategy are configured.
    return [{"action": "find_target", "target": "", "message": ""}] if "find_target" in actions else []


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--platform", choices=["linkedin", "facebook"], required=True)
    parser.add_argument("--slot", type=int, choices=range(1, 6), required=True)
    args = parser.parse_args()

    run_id = os.getenv("GITHUB_RUN_ID", str(uuid.uuid4()))
    live_mode = os.getenv("LIVE_MODE", str(SOCIAL.get("live_mode", False))).lower() == "true"
    client = ComposioClient()

    print(f"ROZHAN Social Outreach | platform={args.platform} | slot={args.slot} | live_mode={live_mode}")
    for item in build_plan(args.platform, args.slot):
        result = client.execute(
            action=f"{args.platform}.{item['action']}",
            payload={"target": item["target"], "message": item["message"]},
            live_mode=live_mode,
        )
        status = result.get("status", "unknown")
        append_action({
            "run_id": run_id,
            "platform": args.platform,
            "slot": str(args.slot),
            "action": item["action"],
            "target": item["target"],
            "message": item["message"],
            "status": status,
            "result": json.dumps(result, ensure_ascii=False),
            "created_at": now_iso(),
        })
        print(json.dumps(result, ensure_ascii=False))

    print("Run completed. No live social action is performed unless LIVE_MODE=true and Composio is configured.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
