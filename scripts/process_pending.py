#!/usr/bin/env python3
"""
Batch processor that selects Japanese-target vtubers from source/vdb.json
and runs scripts/research_one_vtuber.py for up to --count eligible UUIDs.

Selection rules (per spec):
- Read source/vdb.json (read-only).
- Read source/vtuber-readings.json (if missing, treat as empty array).
- Japanese targets: vdb entry where type == "vtuber" and name is dict and name.jp exists and not empty.
- Exclude any UUID that already has a result in vtuber-readings.json with status in {verified,review,unknown}.
- Exclude any UUID for which vtuber-readings.json currently contains pending with last_attempt_result == "error".
- Process up to --count in VDB order.
- For each: call research_one_vtuber.py <uuid>
  - Success criteria:
    * process exit code == 0
    * vtuber-readings.json contains an entry for the uuid after the run
    * that entry's status is one of {"verified","review","unknown"}
    * that entry's checked_at is present and different from previous checked_at (or newly present)
  - On success: count as succeeded
  - On failure: write minimal failure state in vtuber-readings.json (research script does this), and log detailed reason (without storing details in JSON)
- Print header, per-item logs, and summary as specified.
"""
import argparse
import json
import subprocess
import sys
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple

ROOT = Path(__file__).resolve().parent.parent
VDB_PATH = ROOT / "source" / "vdb.json"
READINGS_PATH = ROOT / "source" / "vtuber-readings.json"
RESEARCH_SCRIPT = ROOT / "scripts" / "research_one_vtuber.py"

VALID_TARGET_STATUSES = {"verified", "review", "unknown"}


def load_json_file(path: Path):
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return None
    except json.JSONDecodeError as e:
        print(f"Error: Invalid JSON in {path}: {e}", file=sys.stderr)
        raise


def write_json_file(path: Path, obj):
    with path.open("w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=2)
        f.write("\n")


def iso_now_utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def read_vdb() -> Dict:
    data = load_json_file(VDB_PATH)
    if data is None:
        raise SystemExit(f"Error: {VDB_PATH} not found")
    if not isinstance(data, dict):
        raise SystemExit(f"Error: {VDB_PATH} does not contain a JSON object")
    return data


def read_readings() -> List[Dict]:
    data = load_json_file(READINGS_PATH)
    if data is None:
        return []
    if not isinstance(data, list):
        raise SystemExit(f"Error: {READINGS_PATH} is not a JSON array")
    return data


def vtbs_japanese_targets(vdb: Dict) -> List[Dict]:
    vtbs = vdb.get("vtbs", [])
    targets = []
    for t in vtbs:
        if t.get("type") != "vtuber":
            continue
        name_obj = t.get("name")
        if not isinstance(name_obj, dict):
            continue
        jp = name_obj.get("jp")
        if jp is None:
            continue
        if isinstance(jp, str) and jp.strip() == "":
            continue
        targets.append(t)
    return targets


def build_readings_index(readings: List[Dict]) -> Dict[str, Dict]:
    idx = {}
    for r in readings:
        u = r.get("uuid")
        if u:
            idx[u] = r
    return idx


def run_research(uuid: str) -> Tuple[int, str, str]:
    # Call research script with same environment so OPENROUTER_API_KEY is available
    cmd = [sys.executable, str(RESEARCH_SCRIPT), uuid]
    proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=os.environ)
    return proc.returncode, proc.stdout, proc.stderr


def print_batch_header(vdb_total: int, jap_total: int, readings_total: int,
                       verified_count: int, review_count: int, unknown_count: int,
                       pending_count: int, pending_error_count: int,
                       eligible_before: int, requested_count: int, will_process: int,
                       selected_records: List[Dict]):
    print("BATCH PROCESSING STATUS\n")
    print(f"VDB total records: {vdb_total}")
    print(f"Japanese target records (name.jp): {jap_total}")
    print(f"Processed result records: {readings_total}")
    print(f"verified: {verified_count}")
    print(f"review: {review_count}")
    print(f"unknown: {unknown_count}")
    print(f"pending: {pending_count}")
    print(f"pending with previous error: {pending_error_count}")
    print(f"Eligible for normal batch: {eligible_before}")
    print(f"Requested maximum count: {requested_count}")
    print(f"Will process in this run: {will_process}\n")

    print("Eligible records selected for this batch:")
    for r in selected_records:
        name = (r.get("name") or {}).get("jp") if isinstance(r.get("name"), dict) else None
        print(f"- name={name} uuid={r.get('uuid')}")
    print("")


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--count", type=int, required=True, help="Maximum number of items to process (positive integer)")
    args = p.parse_args()
    if args.count is None or args.count <= 0:
        raise SystemExit("count must be a positive integer")

    # Load VDB and readings
    vdb = read_vdb()
    vtbs = vdb.get("vtbs", [])
    vdb_total = len(vtbs)

    readings = read_readings()
    readings_idx = build_readings_index(readings)
    readings_total = len(readings)

    # Count statuses in readings
    verified_count = sum(1 for r in readings if r.get("status") == "verified")
    review_count = sum(1 for r in readings if r.get("status") == "review")
    unknown_count = sum(1 for r in readings if r.get("status") == "unknown")
    pending_count = sum(1 for r in readings if r.get("status") == "pending")
    pending_error_count = sum(1 for r in readings if r.get("status") == "pending" and r.get("last_attempt_result") == "error")

    jap_targets = vtbs_japanese_targets(vdb)
    jap_total = len(jap_targets)

    # Determine eligible targets: those japanese-target UUIDs that are not already present with status in VALID_TARGET_STATUSES
    eligible = []
    for t in jap_targets:
        uuid = t.get("uuid")
        existing = readings_idx.get(uuid)
        if existing and existing.get("status") in VALID_TARGET_STATUSES:
            continue
        # Exclude pending with last_attempt_result == "error"
        if existing and existing.get("status") == "pending" and existing.get("last_attempt_result") == "error":
            continue
        eligible.append(t)

    eligible_before = len(eligible)
    requested_count = args.count
    to_process = eligible[:requested_count]
    will_process = len(to_process)

    # Print header and selected list
    print_batch_header(vdb_total, jap_total, readings_total,
                       verified_count, review_count, unknown_count,
                       pending_count, pending_error_count,
                       eligible_before, requested_count, will_process,
                       to_process)

    attempted = 0
    succeeded = 0
    failed = 0

    for i, t in enumerate(to_process, start=1):
        attempted += 1
        uuid = t.get("uuid")
        name_jp = (t.get("name") or {}).get("jp") if isinstance(t.get("name"), dict) else None
        print(f"Processing ({i}/{will_process})")
        print(f"name={name_jp}")
        print(f"uuid={uuid}")

        # Previous checked_at from readings (if any)
        prev_checked_at = None
        existing = readings_idx.get(uuid)
        if existing:
            prev_checked_at = existing.get("checked_at")

        ret, out, err = run_research(uuid)

        # After run, reload readings file to inspect whether a result was written/updated
        new_readings = read_readings()
        new_idx = build_readings_index(new_readings)
        new_entry = new_idx.get(uuid)

        success = False
        reason = ""
        if ret != 0:
            # research script signaled an error; per spec, it should have written failure-state, but we still detect
            reason = f"research script exit code {ret}"
        elif new_entry is None:
            reason = "no result written to vtuber-readings.json"
        else:
            new_status = new_entry.get("status")
            new_checked_at = new_entry.get("checked_at")
            if new_status in VALID_TARGET_STATUSES:
                if not new_checked_at:
                    reason = "missing checked_at in result"
                elif new_checked_at == prev_checked_at:
                    reason = "checked_at not updated by this run"
                else:
                    success = True
            else:
                # Could be pending (failure state) written by research script
                if new_status == "pending":
                    # treat as failure per spec
                    reason = "research wrote pending (failure) state"
                else:
                    reason = f"invalid status in result: {new_status}"

        if success:
            succeeded += 1
            print("RESULT: SUCCESS")
            print(f"name={name_jp}")
            print(f"uuid={uuid}")
            print(f"status={new_entry.get('status')}")
            print(f"checked_at={new_entry.get('checked_at')}")
            # Update index for subsequent checks
            readings_idx[uuid] = new_entry
        else:
            failed += 1
            print("RESULT: FAILED")
            print(f"name={name_jp}")
            print(f"uuid={uuid}")
            print(f"exit_code={ret}")
            print(f"reason={reason}")
            if err:
                err_snippet = err.strip()
                if len(err_snippet) > 2000:
                    err_snippet = err_snippet[:2000] + "...(truncated)"
                print("stderr:")
                print(err_snippet)
            # Per spec: failure state should be saved to vtuber-readings.json by research script,
            # but we do not store detailed error info there.

        print("")

    # Final summary
    final_readings = read_readings()
    final_idx = build_readings_index(final_readings)
    final_total = len(final_readings)
    final_verified = sum(1 for r in final_readings if r.get("status") == "verified")
    final_review = sum(1 for r in final_readings if r.get("status") == "review")
    final_unknown = sum(1 for r in final_readings if r.get("status") == "unknown")
    final_pending = sum(1 for r in final_readings if r.get("status") == "pending")
    final_pending_error = sum(1 for r in final_readings if r.get("status") == "pending" and r.get("last_attempt_result") == "error")

    remaining_eligible = 0
    for t in jap_targets:
        uuid = t.get("uuid")
        existing = final_idx.get(uuid)
        if existing and existing.get("status") in VALID_TARGET_STATUSES:
            continue
        # pending with error are excluded
        if existing and existing.get("status") == "pending" and existing.get("last_attempt_result") == "error":
            continue
        remaining_eligible += 1

    print("BATCH SUMMARY\n")
    print(f"VDB total records: {vdb_total}")
    print(f"Japanese target records: {jap_total}")
    print(f"Processed result records: {final_total}")
    print(f"verified: {final_verified}")
    print(f"review: {final_review}")
    print(f"unknown: {final_unknown}")
    print(f"pending: {final_pending}")
    print(f"pending_error: {final_pending_error}")
    print(f"Eligible before batch: {eligible_before}")
    print(f"Requested count: {requested_count}")
    print(f"Attempted this run: {attempted}")
    print(f"Succeeded this run: {succeeded}")
    print(f"Failed this run: {failed}")
    print(f"Remaining eligible: {remaining_eligible}")
    print("")

    # Completion status messages per spec
    if remaining_eligible == 0:
        # Now require that all japanese targets have successful records (verified/review/unknown)
        all_complete = True
        for t in jap_targets:
            uuid = t.get("uuid")
            existing = final_idx.get(uuid)
            if not existing or existing.get("status") not in VALID_TARGET_STATUSES:
                all_complete = False
                break
        if all_complete:
            print("BATCH STATUS: JAPANESE TARGETS COMPLETE")
        else:
            # If none eligible for normal batch because only pending errors remain, show NO ELIGIBLE RECORDS
            if final_pending_error > 0:
                print("BATCH STATUS: NO ELIGIBLE RECORDS")
                print("Pending records remain with previous errors.")
                print("These records are excluded from normal batch processing.")
            else:
                print("BATCH STATUS: MORE ELIGIBLE RECORDS REMAIN")
    else:
        print("BATCH STATUS: MORE ELIGIBLE RECORDS REMAIN")
    print("VDB STATUS: NOT DETERMINED")


if __name__ == "__main__":
    main()
