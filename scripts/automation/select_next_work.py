#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from work_queue_selector import DeliverySnapshot, select_next_action


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Select the next autonomous delivery action from a GitHub snapshot.",
    )
    parser.add_argument(
        "snapshot",
        type=Path,
        help="Path to a JSON snapshot with review_prs, fix_prs, and issues arrays.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    snapshot_payload = json.loads(args.snapshot.read_text(encoding="utf-8"))
    snapshot = DeliverySnapshot.from_dict(snapshot_payload)
    decision = select_next_action(snapshot)
    print(json.dumps(decision.to_dict(), ensure_ascii=True, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
