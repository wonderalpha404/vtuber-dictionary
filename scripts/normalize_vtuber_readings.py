#!/usr/bin/env python3
"""Normalize vtuber-readings.json to the current result schema."""

import json
from pathlib import Path

RESULT_PATH = Path("source/vtuber-readings.json")


def normalize_record(record):
    if not isinstance(record, dict):
        return False

    changed = False

    # Legacy status="unknown" means "researched but no reliable reading".
    # The current schema represents that as pending + confidence=unknown.
    if record.get("status") == "unknown":
        record["status"] = "pending"
        record["reading"] = ""
        record["source"] = ""
        record["source_type"] = ""
        record["confidence"] = ""
        record["last_attempt_result"] = ""
        changed = True

    # confidence is an AI-review-only field. Deterministic kana results do not
    # have an AI confidence value.
    if record.get("source") == "deterministic:kana-only":
        if record.get("confidence") != "":
            record["confidence"] = ""
            changed = True

    # Technical failures use the explicit technical_error result value.
    if (
        record.get("status") == "pending"
        and record.get("last_attempt_result") == "error"
    ):
        record["last_attempt_result"] = "technical_error"
        if record.get("confidence") != "":
            record["confidence"] = ""
        changed = True

    # A researched-but-unknown result is represented by pending + unknown
    # confidence. It must not retain a reading or source.
    if (
        record.get("status") == "pending"
        and record.get("confidence") == "unknown"
    ):
        if record.get("reading") or record.get("source") or record.get("source_type"):
            record["reading"] = ""
            record["source"] = ""
            record["source_type"] = ""
            changed = True

    return changed


def main():
    if not RESULT_PATH.exists():
        print(f"No result file: {RESULT_PATH}")
        return 0

    with RESULT_PATH.open("r", encoding="utf-8") as f:
        results = json.load(f)

    if not isinstance(results, list):
        raise ValueError(f"{RESULT_PATH} must contain a JSON array")

    changed_count = 0

    for record in results:
        if normalize_record(record):
            changed_count += 1

    if changed_count:
        temp_path = RESULT_PATH.with_suffix(RESULT_PATH.suffix + ".tmp")
        with temp_path.open("w", encoding="utf-8") as f:
            json.dump(results, f, ensure_ascii=False, indent=2)
            f.write("\n")
        temp_path.replace(RESULT_PATH)

    print(f"Normalized records: {changed_count}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
