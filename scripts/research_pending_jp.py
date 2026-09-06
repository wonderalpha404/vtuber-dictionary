#!/usr/bin/env python3

import json
import subprocess
import sys
import time
from pathlib import Path


SAMPLE_PATH = Path("source/sample-10-jp.json")
RESEARCH_SCRIPT = Path("scripts/research_one_vtuber.py")
WAIT_SECONDS = 3


def main():
    if not SAMPLE_PATH.exists():
        print(f"ERROR: file not found: {SAMPLE_PATH}", file=sys.stderr)
        return 1

    if not RESEARCH_SCRIPT.exists():
        print(f"ERROR: file not found: {RESEARCH_SCRIPT}", file=sys.stderr)
        return 1

    try:
        with SAMPLE_PATH.open("r", encoding="utf-8") as f:
            data = json.load(f)
    except json.JSONDecodeError as e:
        print(f"ERROR: invalid JSON in {SAMPLE_PATH}: {e}", file=sys.stderr)
        return 1

    if not isinstance(data, list):
        print("ERROR: sample-10-jp.json must contain a JSON array.", file=sys.stderr)
        return 1

    pending = [
        item
        for item in data
        if isinstance(item, dict)
        and item.get("status") == "pending"
        and isinstance(item.get("name"), str)
        and item["name"].strip()
    ]

    print(f"Total entries: {len(data)}")
    print(f"Pending entries: {len(pending)}")

    if not pending:
        print("No pending entries. Nothing to research.")
        return 0

    failures = []

    for index, item in enumerate(pending, start=1):
        name = item["name"].strip()

        print()
        print("=" * 60)
        print(f"[{index}/{len(pending)}] Researching: {name}")
        print("=" * 60)

        result = subprocess.run(
            [sys.executable, str(RESEARCH_SCRIPT), name],
            check=False,
        )

        if result.returncode != 0:
            print(f"FAILED: {name} (exit code {result.returncode})")
            failures.append(name)
        else:
            print(f"SUCCESS: {name}")

        if index < len(pending):
            print(f"Waiting {WAIT_SECONDS} seconds before the next request...")
            time.sleep(WAIT_SECONDS)

    print()
    print("=" * 60)
    print("Batch research finished.")
    print(f"Successful: {len(pending) - len(failures)}")
    print(f"Failed: {len(failures)}")

    if failures:
        print("Failed VTubers:")
        for name in failures:
            print(f"- {name}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
