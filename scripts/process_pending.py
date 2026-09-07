#!/usr/bin/env python3

import argparse
import json
import random
import subprocess
import sys
from pathlib import Path

VDB_PATH = Path("source/vdb.json")
RESULT_PATH = Path("source/vtuber-readings.json")
RESEARCH_SCRIPT = Path("scripts/research_one_vtuber.py")


def load_json(path):
    if not path.exists():
        return None
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def parse_count(value):
    value = str(value).strip().lower()
    if value == "r":
        return "random"
    try:
        count = int(value)
    except ValueError as exc:
        raise ValueError(f"Invalid count: {value!r}. Enter a positive integer or 'r'.") from exc
    if count <= 0:
        raise ValueError("Count must be greater than 0.")
    return count


def is_japanese_target(record):
    if record.get("type") != "vtuber":
        return False
    name = record.get("name")
    return isinstance(name, dict) and isinstance(name.get("jp"), str) and bool(name["jp"].strip())


def get_name(record):
    name = record.get("name")
    return name.get("jp", "") if isinstance(name, dict) else ""


def get_uuid(record):
    return record.get("uuid", "")


def is_completed(result):
    return result.get("status") in {"verified", "review"}


def is_previous_error(result):
    return result.get("status") == "pending" and result.get("last_attempt_result") == "technical_error"


def is_eligible(record, result_by_uuid):
    uuid = get_uuid(record)
    if not uuid:
        return False
    existing = result_by_uuid.get(uuid)
    if existing is None:
        return True
    if is_completed(existing) or is_previous_error(existing):
        return False
    return existing.get("status") == "pending"


def build_result_index(results):
    return {item.get("uuid"): item for item in results if isinstance(item, dict) and item.get("uuid")}


def verify_research_result(uuid, name):
    results = load_json(RESULT_PATH)
    if not isinstance(results, list):
        return False
    for result in results:
        if not isinstance(result, dict):
            continue
        if result.get("uuid") == uuid and result.get("name") == name:
            return result.get("last_attempt_result") == "success" and result.get("status") in {"verified", "review", "pending"}
    return False


def run_research(record):
    uuid = get_uuid(record)
    name = get_name(record)
    print("-" * 60)
    print("PROCESSING")
    print(f"name={name}")
    print(f"uuid={uuid}")
    print("-" * 60)
    try:
        completed = subprocess.run([sys.executable, str(RESEARCH_SCRIPT), uuid, name], text=True, capture_output=True)
    except Exception as exc:
        print(f"RESULT: FAILED\nname={name}\nuuid={uuid}\nexit_code=process_start_error\nreason={type(exc).__name__}: {exc}")
        return False
    stdout = completed.stdout.strip()
    stderr = completed.stderr.strip()
    if completed.returncode == 0 and verify_research_result(uuid, name):
        print("RESULT: SUCCESS")
        print(f"name={name}")
        print(f"uuid={uuid}")
        if stdout:
            print("research output:")
            print(stdout)
        if stderr:
            print("research stderr:")
            print(stderr)
        return True
    print("RESULT: FAILED")
    print(f"name={name}")
    print(f"uuid={uuid}")
    print(f"exit_code={completed.returncode}")
    print("reason=research failed or no valid saved result was found")
    if stdout:
        print("stdout:")
        print(stdout)
    if stderr:
        print("stderr:")
        print(stderr)
    return False


def print_status(vdb_records, japanese_targets, results, eligible, requested):
    counts = {"verified": 0, "review": 0, "pending": 0}
    previous_errors = 0
    for item in results:
        if item.get("status") in counts:
            counts[item["status"]] += 1
        if is_previous_error(item):
            previous_errors += 1
    print("\n" + "=" * 60)
    print("BATCH PROCESSING STATUS")
    print("=" * 60)
    print(f"VDB total records: {len(vdb_records)}")
    print(f"Japanese target records (name.jp): {len(japanese_targets)}")
    print(f"Processed result records: {len(results)}")
    print(f"verified: {counts['verified']}")
    print(f"review: {counts['review']}")
    print(f"pending: {counts['pending']}")
    print(f"pending with previous error: {previous_errors}")
    print(f"Eligible for normal batch: {len(eligible)}")
    print("Requested mode: RANDOM" if requested == "random" else f"Requested maximum count: {requested}")
    print("=" * 60 + "\n")


def select_records(eligible, mode):
    if mode == "random":
        return random.sample(eligible, min(3, len(eligible))) if eligible else []
    return eligible[:mode]


def main():
    parser = argparse.ArgumentParser(description="Process pending Japanese VTuber readings.")
    parser.add_argument("--count", required=True, help="Number of records to process, or 'r' for 3 random records.")
    args = parser.parse_args()
    try:
        requested = parse_count(args.count)
    except ValueError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    vdb = load_json(VDB_PATH)
    if not isinstance(vdb, dict) or not isinstance(vdb.get("vtbs"), list):
        print(f"ERROR: Invalid VDB JSON: {VDB_PATH}", file=sys.stderr)
        return 1
    results = load_json(RESULT_PATH)
    if results is None:
        results = []
    if not isinstance(results, list):
        print(f"ERROR: Invalid result JSON: {RESULT_PATH}", file=sys.stderr)
        return 1

    vdb_records = vdb["vtbs"]
    result_by_uuid = build_result_index(results)
    japanese_targets = [r for r in vdb_records if is_japanese_target(r)]
    eligible = [r for r in japanese_targets if is_eligible(r, result_by_uuid)]
    print_status(vdb_records, japanese_targets, results, eligible, requested)
    selected = select_records(eligible, requested)
    if not selected:
        print("NO ELIGIBLE RECORDS")
        return 0

    print("RANDOMLY SELECTED 3 RECORDS:" if requested == "random" else "SELECTED RECORDS:")
    for record in selected:
        print(f"- name={get_name(record)} uuid={get_uuid(record)}")
    print()

    succeeded = 0
    failed = 0
    for index, record in enumerate(selected, 1):
        print(f"\nProcessing ({index}/{len(selected)})")
        if run_research(record):
            succeeded += 1
        else:
            failed += 1

    updated_results = load_json(RESULT_PATH)
    if isinstance(updated_results, list):
        results = updated_results
    result_by_uuid = build_result_index(results)
    remaining = [r for r in japanese_targets if is_eligible(r, result_by_uuid)]
    counts = {"verified": 0, "review": 0, "pending": 0}
    pending_errors = 0
    for item in results:
        if item.get("status") in counts:
            counts[item["status"]] += 1
        if is_previous_error(item):
            pending_errors += 1

    print("\n" + "=" * 60)
    print("BATCH SUMMARY")
    print("=" * 60)
    print(f"VDB total records: {len(vdb_records)}")
    print(f"Japanese target records: {len(japanese_targets)}")
    print(f"Processed result records: {len(results)}")
    print(f"verified: {counts['verified']}")
    print(f"review: {counts['review']}")
    print(f"pending: {counts['pending']}")
    print(f"pending_error: {pending_errors}")
    print(f"Eligible before batch: {len(eligible)}")
    print("Requested mode: RANDOM" if requested == "random" else f"Requested count: {requested}")
    print(f"Attempted this run: {len(selected)}")
    print(f"Succeeded this run: {succeeded}")
    print(f"Failed this run: {failed}")
    print(f"Remaining eligible: {len(remaining)}")
    if failed:
        print("BATCH STATUS: COMPLETED WITH FAILURES")
    elif remaining:
        print("BATCH STATUS: MORE ELIGIBLE RECORDS REMAIN")
    else:
        print("BATCH STATUS: ALL CURRENT ELIGIBLE RECORDS COMPLETE")
    print("VDB STATUS: NOT DETERMINED")
    print("=" * 60)
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
