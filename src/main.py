import argparse
import json
import os
import uuid
from pathlib import Path

from .composio_client import ComposioClient
from .state import append_action, now_iso

ROOT = Path(__file__).resolve().parents[1]
SOCIAL = json.loads((ROOT / "config/social.json").read_text(encoding="utf-8"))


def run_slot(
    platform: str,
    slot: int,
    run_id: str | None = None,
    *,
    target: str = "",
    target_name: str = "",
) -> dict[str, str]:
    run_id = run_id or os.getenv("GITHUB_RUN_ID", str(uuid.uuid4()))
    live_mode = os.getenv("LIVE_MODE", str(SOCIAL.get("live_mode", False))).lower() == "true"
    client = ComposioClient()

    # Discovery is already performed by the hourly batch. This step records the
    # selected target and keeps execution behind the explicit LIVE_MODE switch.
    action = "find_target"
    payload = {"target": target, "target_name": target_name, "message": ""}
    result = client.execute(
        action=f"{platform}.{action}",
        payload=payload,
        live_mode=live_mode,
    )
    append_action({
        "run_id": run_id,
        "platform": platform,
        "slot": str(slot),
        "action": action,
        "target": target,
        "message": "",
        "status": result.get("status", "unknown"),
        "result": json.dumps(result, ensure_ascii=False),
        "created_at": now_iso(),
    })
    print(f"ROZHAN Social Outreach | platform={platform} | slot={slot} | target={target} | live_mode={live_mode}")
    print(json.dumps(result, ensure_ascii=False))
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--platform", choices=["linkedin", "facebook"], required=True)
    parser.add_argument("--slot", type=int, choices=range(1, 6), required=True)
    parser.add_argument("--run-id", default=None)
    parser.add_argument("--target", default="")
    parser.add_argument("--target-name", default="")
    args = parser.parse_args()
    run_slot(args.platform, args.slot, args.run_id, target=args.target, target_name=args.target_name)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
