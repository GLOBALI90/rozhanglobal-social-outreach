import os
import uuid

from .main import run_slot


def main() -> int:
    run_id = os.getenv("GITHUB_RUN_ID", str(uuid.uuid4()))
    results = []
    for platform in ("facebook", "linkedin"):
        for slot in range(1, 6):
            results.append(run_slot(platform, slot, run_id))

    print(f"HOURLY BATCH COMPLETE | records={len(results)} | facebook=5 | linkedin=5")
    if len(results) != 10:
        raise RuntimeError(f"Expected exactly 10 records, got {len(results)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
