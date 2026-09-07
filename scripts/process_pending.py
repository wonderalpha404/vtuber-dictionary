#!/usr/bin/env python3

import argparse
import json
import random
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path


VDB_PATH = Path("source/vdb.json")
RESULT_PATH = Path("source/vtuber-readings.json")
RESEARCH_SCRIPT = Path("scripts/research_one_vtuber.py")


def utc_now():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def load_json(path):
    if not path.exists():
        return None

    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def save_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)

    temp_path = path.with_suffix(path.suffix + ".tmp")

    with temp_path.open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.write("\n")

    temp_path.replace(path)


def parse_count(value):
    """
    数字:
        1, 10, 100 ...

    r:
        ランダム3件
    """
    value = str(value).strip().lower()

    if value == "r":
        return "random"

    try:
        count = int(value)
    except ValueError:
        raise ValueError(
            f"Invalid count: {value!r}. "
            "Enter a positive integer or 'r'."
        )

    if count <= 0:
        raise ValueError("Count must be greater than 0.")

    return count


def is_japanese_target(record):
    """
    日本人VTuberの判定。

    現在のVDBには nationality フィールドがないため、
    既存仕様どおり以下を対象条件とする。

      type == "vtuber"
      name.jp が存在し、空ではない
    """
    if record.get("type") != "vtuber":
        return False

    name = record.get("name")

    if not isinstance(name, dict):
        return False

    jp_name = name.get("jp")

    return isinstance(jp_name, str) and bool(jp_name.strip())


def get_name(record):
    name = record.get("name")

    if isinstance(name, dict):
        return name.get("jp", "")

    return ""


def get_uuid(record):
    return record.get("uuid", "")


def is_completed(result):
    """
    正常に研究完了した状態。

    これらは通常バッチでは再処理しない。
    """
    return result.get("status") in {
        "verified",
        "review",
        "unknown",
    }


def is_previous_error(result):
    """
    前回の技術的失敗。

    status は pending のまま。
    normal batch では再処理しない。
    """
    return (
        result.get("status") == "pending"
        and result.get("last_attempt_result") == "error"
    )


def is_eligible(record, result_by_uuid):
    """
    通常バッチで処理可能か判定する。

    対象:
      - 結果ファイルに存在しない
      - pending だが、まだ一度もエラーになっていない

    対象外:
      - verified
      - review
      - unknown
      - pending + previous error
    """
    uuid = get_uuid(record)

    if not uuid:
        return False

    existing = result_by_uuid.get(uuid)

    if existing is None:
        return True

    if is_completed(existing):
        return False

    if is_previous_error(existing):
        return False

    if existing.get("status") == "pending":
        return True

    return False


def build_result_index(results):
    return {
        item.get("uuid"): item
        for item in results
        if isinstance(item, dict) and item.get("uuid")
    }


def print_status(
    vdb_records,
    japanese_targets,
    results,
    result_by_uuid,
    eligible,
    requested,
    selection_mode,
):
    status_counts = {
        "verified": 0,
        "review": 0,
        "unknown": 0,
        "pending": 0,
    }

    previous_errors = 0

    for item in results:
        status = item.get("status")

        if status in status_counts:
            status_counts[status] += 1

        if is_previous_error(item):
            previous_errors += 1

    print()
    print("=" * 60)
    print("BATCH PROCESSING STATUS")
    print("=" * 60)

    print(f"VDB total records: {len(vdb_records)}")
    print(f"Japanese target records (name.jp): {len(japanese_targets)}")
    print(f"Processed result records: {len(results)}")

    print(f"verified: {status_counts['verified']}")
    print(f"review: {status_counts['review']}")
    print(f"unknown: {status_counts['unknown']}")
    print(f"pending: {status_counts['pending']}")
    print(f"pending with previous error: {previous_errors}")

    print(f"Eligible for normal batch: {len(eligible)}")

    if selection_mode == "random":
        print("Requested mode: RANDOM")
        print("Random selection count: 3")
    else:
        print(f"Requested maximum count: {requested}")

    print("=" * 60)
    print()


def select_records(eligible, mode):
    if mode == "random":
        count = min(3, len(eligible))

        if count == 0:
            return []

        return random.sample(eligible, count)

    return eligible[:mode]


def verify_research_result(uuid, name):
    """
    research_one_vtuber.py が exit code 0 で終了した場合でも、
    実際の正常結果を確認する。

    Returns:
        True: 正常結果を確認
        False: 正常結果を確認できない
    """
    results = load_json(RESULT_PATH)

    if not isinstance(results, list):
        return False

    for result in results:
        if not isinstance(result, dict):
            continue

        if result.get("uuid") != uuid:
            continue

        if result.get("name") != name:
            continue

        status = result.get("status")
        last_attempt_result = result.get("last_attempt_result")

        if status not in {"verified", "review", "unknown"}:
            return False

        if last_attempt_result != "success":
            return False

        return True

    return False


def run_research(record):
    uuid = get_uuid(record)
    name = get_name(record)

    print("-" * 60)
    print("PROCESSING")
    print(f"name={name}")
    print(f"uuid={uuid}")
    print("-" * 60)

    started_at = utc_now()

    try:
        completed = subprocess.run(
            [
                sys.executable,
                str(RESEARCH_SCRIPT),
                uuid,
                name,
            ],
            text=True,
            capture_output=True,
        )
    except Exception as exc:
        print("RESULT: FAILED")
        print(f"name={name}")
        print(f"uuid={uuid}")
        print("exit_code=process_start_error")
        print(f"reason={type(exc).__name__}: {exc}")
        print(f"started_at={started_at}")
        print(f"finished_at={utc_now()}")
        return False

    stdout = completed.stdout.strip()
    stderr = completed.stderr.strip()

    if completed.returncode == 0:
        if verify_research_result(uuid, name):
            print("RESULT: SUCCESS")
            print(f"name={name}")
            print(f"uuid={uuid}")

            if stdout:
                print("research output:")
                print(stdout)

            if stderr:
                print("research stderr:")
                print(stderr)

            print(f"started_at={started_at}")
            print(f"finished_at={utc_now()}")

            return True

        print("RESULT: FAILED")
        print(f"name={name}")
        print(f"uuid={uuid}")
        print(f"exit_code={completed.returncode}")
        print(
            "reason=research exited 0 but "
            "no valid saved result was found"
        )
        print(f"started_at={started_at}")
        print(f"finished_at={utc_now()}")

        if stdout:
            print("stdout:")
            print(stdout)

        if stderr:
            print("stderr:")
            print(stderr)

        return False

    print("RESULT: FAILED")
    print(f"name={name}")
    print(f"uuid={uuid}")
    print(f"exit_code={completed.returncode}")
    print(
        f"reason=research script exit code "
        f"{completed.returncode}"
    )
    print(f"started_at={started_at}")
    print(f"finished_at={utc_now()}")

    if stdout:
        print("stdout:")
        print(stdout)

    if stderr:
        print("stderr:")
        print(stderr)

    return False


def main():
    parser = argparse.ArgumentParser(
        description=(
            "Process pending Japanese VTuber readings. "
            "Use a number for sequential processing or 'r' "
            "for 3 random eligible records."
        )
    )

    parser.add_argument(
        "--count",
        required=True,
        help="Number of records to process, or 'r' for 3 random records.",
    )

    args = parser.parse_args()

    try:
        requested = parse_count(args.count)
    except ValueError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    # ------------------------------------------------------------
    # Load VDB
    # ------------------------------------------------------------

    vdb = load_json(VDB_PATH)

    if not isinstance(vdb, dict):
        print(
            f"ERROR: Invalid VDB JSON: {VDB_PATH}",
            file=sys.stderr,
        )
        return 1

    vdb_records = vdb.get("vtbs")

    if not isinstance(vdb_records, list):
        print(
            "ERROR: source/vdb.json does not contain a valid "
            "'vtbs' array.",
            file=sys.stderr,
        )
        return 1

    # ------------------------------------------------------------
    # Load result file
    # ------------------------------------------------------------

    results = load_json(RESULT_PATH)

    if results is None:
        results = []

    if not isinstance(results, list):
        print(
            f"ERROR: Invalid result JSON: {RESULT_PATH}",
            file=sys.stderr,
        )
        return 1

    result_by_uuid = build_result_index(results)

    # ------------------------------------------------------------
    # Japanese targets
    # ------------------------------------------------------------

    japanese_targets = [
        record
        for record in vdb_records
        if is_japanese_target(record)
    ]

    # ------------------------------------------------------------
    # Eligible records
    # ------------------------------------------------------------

    eligible = [
        record
        for record in japanese_targets
        if is_eligible(record, result_by_uuid)
    ]

    selection_mode = requested

    print_status(
        vdb_records=vdb_records,
        japanese_targets=japanese_targets,
        results=results,
        result_by_uuid=result_by_uuid,
        eligible=eligible,
        requested=requested,
        selection_mode=selection_mode,
    )

    # ------------------------------------------------------------
    # Select records
    # ------------------------------------------------------------

    selected = select_records(eligible, selection_mode)

    if not selected:
        print("NO ELIGIBLE RECORDS")

        if len(japanese_targets) == 0:
            print(
                "No Japanese target records were found "
                "(type=vtuber and non-empty name.jp)."
            )
        elif len(eligible) == 0:
            print(
                "All Japanese target records are already processed "
                "or are previous failures."
            )

        print()
        print("BATCH STATUS: NO ELIGIBLE RECORDS")
        print("VDB STATUS: NOT DETERMINED")
        return 0

    # ------------------------------------------------------------
    # Show selection
    # ------------------------------------------------------------

    if selection_mode == "random":
        print("RANDOMLY SELECTED 3 RECORDS:")
    else:
        print("SELECTED RECORDS:")

    for record in selected:
        print(
            f"- name={get_name(record)} "
            f"uuid={get_uuid(record)}"
        )

    print()

    # ------------------------------------------------------------
    # Process
    # ------------------------------------------------------------

    attempted = 0
    succeeded = 0
    failed = 0

    for index, record in enumerate(selected, start=1):
        print()
        print(f"Processing ({index}/{len(selected)})")

        attempted += 1

        if run_research(record):
            succeeded += 1
        else:
            failed += 1

    # ------------------------------------------------------------
    # Reload results after processing
    # ------------------------------------------------------------

    updated_results = load_json(RESULT_PATH)

    if isinstance(updated_results, list):
        results = updated_results

    result_by_uuid = build_result_index(results)

    remaining_eligible = [
        record
        for record in japanese_targets
        if is_eligible(record, result_by_uuid)
    ]

    # ------------------------------------------------------------
    # Summary
    # ------------------------------------------------------------

    print()
    print("=" * 60)
    print("BATCH SUMMARY")
    print("=" * 60)

    print(f"VDB total records: {len(vdb_records)}")
    print(f"Japanese target records: {len(japanese_targets)}")
    print(f"Processed result records: {len(results)}")

    final_counts = {
        "verified": 0,
        "review": 0,
        "unknown": 0,
        "pending": 0,
    }

    pending_errors = 0

    for item in results:
        status = item.get("status")

        if status in final_counts:
            final_counts[status] += 1

        if is_previous_error(item):
            pending_errors += 1

    print(f"verified: {final_counts['verified']}")
    print(f"review: {final_counts['review']}")
    print(f"unknown: {final_counts['unknown']}")
    print(f"pending: {final_counts['pending']}")
    print(f"pending_error: {pending_errors}")

    print(f"Eligible before batch: {len(eligible)}")

    if selection_mode == "random":
        print("Requested mode: RANDOM")
        print("Random selection count: 3")
    else:
        print(f"Requested count: {selection_mode}")

    print(f"Attempted this run: {attempted}")
    print(f"Succeeded this run: {succeeded}")
    print(f"Failed this run: {failed}")

    print(f"Remaining eligible: {len(remaining_eligible)}")

    if failed > 0:
        print("BATCH STATUS: COMPLETED WITH FAILURES")
    elif remaining_eligible:
        print("BATCH STATUS: MORE ELIGIBLE RECORDS REMAIN")
    else:
        print("BATCH STATUS: ALL CURRENT ELIGIBLE RECORDS COMPLETE")

    print("VDB STATUS: NOT DETERMINED")
    print("=" * 60)

    # 技術的失敗があった場合でも、結果ファイルへの
    # failure state 保存は research_one_vtuber.py 側で行う。
    #
    # バッチ全体としては失敗を明示する。
    return 1 if failed > 0 else 0


if __name__ == "__main__":
    sys.exit(main())
