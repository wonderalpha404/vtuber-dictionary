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
  - On failure: do NOT change status; set last_attempted_at, last_attempt_result="error"
    and append stderr/stdout to notes.
- Writes source/sample-10-jp.json only if changes are made.

The script also prints detailed progress information to the GitHub Actions log.
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
VDB_PATH = ROOT / "source" / "vdb.json"
RESEARCH_SCRIPT = ROOT / "scripts" / "research_one_vtuber.py"

VALID_TARGET_STATUSES = {"verified", "review", "unknown"}


def load_sample():
    with SAMPLE_PATH.open("r", encoding="utf-8") as f:
        return json.load(f)


def load_vdb_count() -> Optional[int]:
    """Return the number of records in source/vdb.json if available."""
    if not VDB_PATH.exists():
        return None

    try:
        with VDB_PATH.open("r", encoding="utf-8") as f:
            data = json
