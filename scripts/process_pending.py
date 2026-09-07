#!/usr/bin/env python3
"""
Batch processor: call existing scripts/research_one_vtuber.py for pending entries.

Behavior:
- Operates only on source/sample-10-jp.json.
- Select candidates where status == "pending" and last_attempt_result != "error".
- For each candidate up to --count:
  - Call RESEARCH_SCRIPT with the vtuber name once.
  - Success criteria:
      * research script exit code == 0
      * target record exists after run
      * target record status is one of ("verified","review","unknown")
      * checked_at was updated by this run (different from previous checked_at)
  - On success: clear last_attempt_result/last_attempted_at if present.
  - On failure: do NOT change status; set last_attempted_at,
    last_attempt_result="error" and append stderr/stdout to notes.
- Writes source/sample-10-jp.json when processing produces changes.

This script also prints detailed progress information to the GitHub Actions log.
"""

import argparse
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional


# Repository root
ROOT = Path(__file__).resolve().parent.parent

SAMPLE_PATH = ROOT / "source" / "sample-10-jp.json"
VDB_PATH = ROOT / "source" / "vdb.json"
RESEARCH_SCRIPT = ROOT / "scripts" / "research_one_vtuber.py"

VALID_TARGET_STATUSES = {"verified", "review", "unknown"}


def load_sample():
    with SAMPLE_PATH.open("r", encoding="utf-8") as f:
        return json.load(f)


def load_vdb_count() -> Optional[int]:
    """
    Return the number of records in source/vdb.json if available.

    This is informational only.
    The VDB itself is never modified by this script.
    """
    if not VDB_PATH.exists():
        return None

    try:
        with VDB_PATH.open("r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception:
        return None

    if isinstance(data, list):
        return len(data)

    if isinstance(data, dict):
        for key in ("data", "items", "vtubers", "results"):
            value = data.get(key)
            if isinstance(value, list):
                return len(value)

    return None


def write_sample(data):
    with SAMPLE_PATH.open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.write("\n")


def iso_now():
    return datetime.now(timezone.utc).astimezone().isoformat()


def run_research_for(name: str):
    cmd = [
        sys.executable,
        str(RESEARCH_SCRIPT),
        name,
    ]

    proc = subprocess.run(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env=os.environ,
    )

    return proc.returncode, proc.stdout, proc.stderr


def find_record_by_name(sample: list, name: str) -> Optional[dict]:
    for rec in sample:
        if rec.get("name") == name:
            return rec

    return None


def get_counts(sample: list):
    total = len(sample)

    verified = 0
    review = 0
    unknown = 0
    pending = 0
    pending_error = 0
    eligible = 0

    for rec in sample:
        status = rec.get("status")

        if status == "verified":
            verified += 1

        elif status == "review":
            review += 1

        elif status == "unknown":
            unknown += 1

        elif status == "pending":
            pending += 1

            if rec.get("last_attempt_result") == "error":
                pending_error += 1
            else:
                eligible += 1

    return {
        "total": total,
        "verified": verified,
        "review": review,
        "unknown": unknown,
        "pending": pending,
        "pending_error": pending_error,
        "eligible": eligible,
    }


def print_initial_status(sample: list, count: int, vdb_count: Optional[int]):
    counts = get_counts(sample)

    print("")
    print("========================================")
    print("BATCH PROCESSING STATUS")
    print("========================================")

    print(f"Dataset: {SAMPLE_PATH.relative_to(ROOT)}")
    print(f"Total records in current dataset: {counts['total']}")

    if vdb_count is not None:
        print(f"VDB total records: {vdb_count}")
    else:
        print("VDB total records: unavailable")

    print("")
    print(f"verified: {counts['verified']}")
    print(f"review: {counts['review']}")
    print(f"unknown: {counts['unknown']}")
    print(f"pending: {counts['pending']}")
    print(f"pending with previous error: {counts['pending_error']}")
    print(f"Eligible for normal batch: {counts['eligible']}")
    print(f"Requested maximum count: {count}")

    will_process = min(counts["eligible"], count)

    print(f"Will process in this run: {will_process}")

    print("")
    print("VDB completion status: NOT DETERMINED BY CURRENT DATASET")
    print("========================================")
    print("")


def main():
    parser = argparse.ArgumentParser()

    parser.add_argument(
        "--count",
        type=int,
        required=True,
        help="最大処理件数（正の整数）",
    )

    args = parser.parse_args()

    if args.count <= 0:
        raise SystemExit("count must be a positive integer")

    # Load current sample dataset.
    sample = load_sample()

    # VDB count is informational only.
    vdb_count = load_vdb_count()

    # Show status before processing.
    print_initial_status(
        sample,
        args.count,
        vdb_count,
    )

    # Build candidate list in original order.
    candidates = []

    for rec in sample:
        if rec.get("status") != "pending":
            continue

        if rec.get("last_attempt_result") == "error":
            continue

        candidates.append(rec)

    eligible_before_batch = len(candidates)

    to_process = candidates[:args.count]

    # ---------------------------------------------------------
    # No eligible records
    # ---------------------------------------------------------

    if not to_process:
        counts = get_counts(sample)

        print("========================================")
        print("NO ELIGIBLE RECORDS")
        print("========================================")

        if counts["pending"] == 0:
            print("BATCH STATUS: CURRENT DATASET COMPLETE")
            print(
                "There are no pending records remaining "
                "in the current dataset."
            )

        elif counts["pending_error"] == counts["pending"]:
            print("BATCH STATUS: NO ELIGIBLE RECORDS")
            print(
                "Pending records exist, but all remaining pending "
                "records are previously failed records."
            )

        else:
            print("BATCH STATUS: NO ELIGIBLE RECORDS")
            print(
                "There are currently no records eligible "
                "for normal batch processing."
            )

        print("")
        print(
            "This does NOT mean the entire VDB has been processed."
        )
        print("VDB STATUS: NOT DETERMINED")

        print("========================================")

        return

    # ---------------------------------------------------------
    # Process records
    # ---------------------------------------------------------

    changes_made = False
    attempted = 0
    succeeded = 0
    failed = 0

    print("Eligible records selected for this batch:")

    for rec in to_process:
        print(
            f"- name={rec.get('name')} "
            f"uuid={rec.get('uuid')}"
        )

    print("")

    for rec in to_process:
        name = rec.get("name")
        uuid = rec.get("uuid")

        attempted += 1

        print("========================================")
        print(f"Processing ({attempted}/{len(to_process)})")
        print(f"name={name}")
        print(f"uuid={uuid}")
        print("========================================")

        prev_checked_at = rec.get("checked_at")

        ret, out, err = run_research_for(name)

        # Reload the dataset because research_one_vtuber.py
        # modifies the JSON file itself.
        sample_after = load_sample()

        matched = find_record_by_name(
            sample_after,
            name,
        )

        success = False

        if ret == 0 and matched is not None:
            new_status = matched.get("status")
            new_checked_at = matched.get("checked_at")

            if (
                new_status in VALID_TARGET_STATUSES
                and new_checked_at
                and new_checked_at != prev_checked_at
            ):
                success = True

        # -----------------------------------------------------
        # Success
        # -----------------------------------------------------

        if success:
            succeeded += 1

            print("")
            print("RESULT: SUCCESS")
            print(f"name={name}")
            print(f"uuid={uuid}")
            print(f"status={matched.get('status')}")
            print(f"checked_at={matched.get('checked_at')}")

            # Clear previous error markers if present.
            for i, current_rec in enumerate(sample_after):
                if current_rec.get("name") == name:
                    sample_after[i].pop(
                        "last_attempt_result",
                        None,
                    )
                    sample_after[i].pop(
                        "last_attempted_at",
                        None,
                    )
                    break

            write_sample(sample_after)
            changes_made = True

        # -----------------------------------------------------
        # Failure
        # -----------------------------------------------------

        else:
            failed += 1

            now = iso_now()

            print("")
            print("RESULT: FAILED")
            print(f"name={name}")
            print(f"uuid={uuid}")
            print(f"exit_code={ret}")

            if out:
                print("")
                print("stdout:")
                print(out.strip())

            if err:
                print("")
                print("stderr:")
                print(err.strip())

            note_lines = [
                (
                    f"Auto-batch attempt at {now}: "
                    f"research_one_vtuber.py exit_code={ret}"
                )
            ]

            if out:
                note_lines.append(
                    f"stdout: {out.strip()}"
                )

            if err:
                note_lines.append(
                    f"stderr: {err.strip()}"
                )

            updated = False

            for i, current_rec in enumerate(sample_after):
                if current_rec.get("name") == name:
                    existing_notes = current_rec.get(
                        "notes",
                        "",
                    )

                    append_text = "\n".join(note_lines)

                    if existing_notes:
                        current_rec["notes"] = (
                            existing_notes
                            + "\n"
                            + append_text
                        )
                    else:
                        current_rec["notes"] = append_text

                    current_rec["last_attempted_at"] = now
                    current_rec["last_attempt_result"] = "error"

                    updated = True
                    break

            if updated:
                write_sample(sample_after)
                changes_made = True

                print("")
                print(
                    "Recorded failure in sample dataset."
                )
                print(
                    "Status remains pending."
                )

            else:
                print(
                    "WARNING: Could not locate record after run "
                    "to mark failure."
                )

    # ---------------------------------------------------------
    # Final summary
    # ---------------------------------------------------------

    final_sample = load_sample()
    final_counts = get_counts(final_sample)

    remaining_eligible = final_counts["eligible"]

    print("")
    print("========================================")
    print("BATCH SUMMARY")
    print("========================================")

    print(
        f"Current dataset: "
        f"{SAMPLE_PATH.relative_to(ROOT)}"
    )

    print(
        f"Total records: "
        f"{final_counts['total']}"
    )

    if vdb_count is not None:
        print(
            f"VDB total records: "
            f"{vdb_count}"
        )

    print(
        f"verified: "
        f"{final_counts['verified']}"
    )

    print(
        f"review: "
        f"{final_counts['review']}"
    )

    print(
        f"unknown: "
        f"{final_counts['unknown']}"
    )

    print(
        f"pending: "
        f"{final_counts['pending']}"
    )

    print(
        f"pending_error: "
        f"{final_counts['pending_error']}"
    )

    print(
        f"Eligible before batch: "
        f"{eligible_before_batch}"
    )

    print(
        f"Requested count: "
        f"{args.count}"
    )

    print(
        f"Attempted this run: "
        f"{attempted}"
    )

    print(
        f"Succeeded this run: "
        f"{succeeded}"
    )

    print(
        f"Failed this run: "
        f"{failed}"
    )

    print(
        f"Remaining eligible: "
        f"{remaining_eligible}"
    )

    print("")

    if remaining_eligible > 0:
        print(
            "BATCH STATUS: MORE ELIGIBLE RECORDS REMAIN"
        )
        print(
            "This batch processed only the requested "
            "number of records."
        )

    elif final_counts["pending"] == 0:
        print(
            "BATCH STATUS: CURRENT DATASET COMPLETE"
        )
        print(
            "There are no pending records remaining "
            "in the current dataset."
        )

    elif final_counts["pending_error"] == final_counts["pending"]:
        print(
            "BATCH STATUS: NO ELIGIBLE RECORDS"
        )
        print(
            "All remaining pending records have previous "
            "errors and are excluded from normal batch processing."
        )

    else:
        print(
            "BATCH STATUS: NO ELIGIBLE RECORDS"
        )

    print("")
    print("VDB STATUS: NOT DETERMINED")
    print(
        "Completion of the current dataset does not prove "
        "that the entire VDB has been processed."
    )

    print("========================================")

    if not changes_made:
        print(
            "No changes were made to the sample file."
        )


if __name__ == "__main__":
    main()
