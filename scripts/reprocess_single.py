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
    (Even if status value remains the same, an updated checked_at counts as success.)
  - On success: clear last_attempt_result/last_attempted_at if present.
  - On failure: do NOT change status; set last_attempted_at, last_attempt_result="error" and append stderr/stdout to notes.
- Writes source/sample-10-jp.json only if changes are made.
"""
import argparse
import json
import subprocess
import sys
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

# REPO root (parent of the 'scripts' directory)
ROOT = Path(__file__).resolve().parent.parent
SAMPLE_PATH = ROOT / "source" / "sample-10-jp.json"
RESEARCH_SCRIPT = ROOT / "scripts" / "research_one_vtuber.py"

VALID_TARGET_STATUSES = {"verified", "review", "unknown"}


def load_sample():
    with SAMPLE_PATH.open("r", encoding="utf-8") as f:
        return json.load(f)


def write_sample(data):
    with SAMPLE_PATH.open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.write("\n")


def iso_now():
    return datetime.now(timezone.utc).astimezone().isoformat()


def run_research_for(name: str) -> (int, str, str):
    cmd = [sys.executable, str(RESEARCH_SCRIPT), name]
    proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=os.environ)
    return proc.returncode, proc.stdout, proc.stderr


def find_record_by_name(sample: list, name: str) -> Optional[dict]:
    for rec in sample:
        if rec.get("name") == name:
            return rec
    return None


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--count", type=int, required=True, help="最大処理件数（正の整数）")
    args = p.parse_args()
    if args.count is None or args.count <= 0:
        raise SystemExit("count must be a positive integer")

    # Load sample
    sample = load_sample()

    # Build candidate list in original order
    candidates = []
    for rec in sample:
        if rec.get("status") != "pending":
            continue
        if rec.get("last_attempt_result") == "error":
            # Exclude previously failed ones from normal batch
            continue
        candidates.append(rec)

    to_process = candidates[: args.count]

    if not to_process:
        print("No pending records eligible for processing.")
        return

    changes_made = False
    attempted = 0
    succeeded = 0
    failed = 0

    for rec in to_process:
        name = rec.get("name")
        uuid = rec.get("uuid")
        attempted += 1
        print(f"Processing ({attempted}/{len(to_process)}): name={name} uuid={uuid}")

        prev_checked_at = rec.get("checked_at")
        prev_status = rec.get("status")

        ret, out, err = run_research_for(name)

        # reload sample to inspect result
        sample_after = load_sample()
        matched = find_record_by_name(sample_after, name)

        success = False
        if ret == 0 and matched is not None:
            new_status = matched.get("status")
            new_checked_at = matched.get("checked_at")
            if new_status in VALID_TARGET_STATUSES and new_checked_at and new_checked_at != prev_checked_at:
                success = True

        if success:
            print(f"SUCCESS: {name} -> status={matched.get('status')} checked_at={matched.get('checked_at')}")
            # Clear previous error markers if any
            updated = False
            for i, r in enumerate(sample_after):
                if r.get("name") == name:
                    if "last_attempt_result" in sample_after[i] or "last_attempted_at" in sample_after[i]:
                        sample_after[i].pop("last_attempt_result", None)
                        sample_after[i].pop("last_attempted_at", None)
                        updated = True
                    break
            if updated:
                write_sample(sample_after)
                changes_made = True
            else:
                # Even if no clearing needed, ensure we keep any other modifications saved
                write_sample(sample_after)
                changes_made = True
            succeeded += 1
        else:
            # failure: do not change status, record failure metadata and append notes
            failed += 1
            now = iso_now()
            note_lines = []
            note_lines.append(f"Auto-batch attempt at {now}: research_one_vtuber.py exit_code={ret}")
            if out:
                note_lines.append(f"stdout: {out.strip()}")
            if err:
                note_lines.append(f"stderr: {err.strip()}")

            updated = False
            for i, r in enumerate(sample_after):
                if r.get("name") == name:
                    # preserve existing notes and append
                    existing_notes = sample_after[i].get("notes", "")
                    append_text = "\n".join(note_lines)
                    if existing_notes:
                        sample_after[i]["notes"] = existing_notes + "\n" + append_text
                    else:
                        sample_after[i]["notes"] = append_text
                    sample_after[i]["last_attempted_at"] = now
                    sample_after[i]["last_attempt_result"] = "error"
                    updated = True
                    break

            if updated:
                write_sample(sample_after)
                changes_made = True
                print(f"Marked as error (left status pending): {name}")
            else:
                print(f"Warning: Could not locate record after run to mark failure: {name}")

    print(f"Summary: attempted={attempted} succeeded={succeeded} failed={failed}")
    if not changes_made:
        print("No changes were made to the sample file.")
    # Exit zero to let workflow handle commits; individual failures were recorded in the sample file.

if __name__ == "__main__":
    main()
