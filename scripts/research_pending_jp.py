#!/usr/bin/env python3

import json
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
import unicodedata


SAMPLE_PATH = Path("source/sample-10-jp.json")
RESEARCH_SCRIPT = Path("scripts/research_one_vtuber.py")
WAIT_SECONDS = 3


def is_kana_only(text):
    """Check if text contains only hiragana and katakana characters."""
    if not text or not isinstance(text, str):
        return False
    
    for char in text:
        category = unicodedata.category(char)
        # Hiragana: 3040-309F, Katakana: 30A0-30FF
        code_point = ord(char)
        is_hiragana = 0x3040 <= code_point <= 0x309F
        is_katakana = 0x30A0 <= code_point <= 0x30FF
        
        if not (is_hiragana or is_katakana):
            return False
    
    return True


def process_kana_only(item):
    """Process kana-only name by setting it as reading automatically."""
    name = item["name"].strip()
    item["reading"] = name
    item["status"] = "verified"
    item["confidence"] = "high"
    item["source"] = "name itself"
    item["source_type"] = "automatic"
    item["notes"] = "名前がひらがな・カタカナのみのため、検索せず名前自体を読みとして設定した"
    item["checked_at"] = datetime.now().isoformat()
    return item


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

    # Filter pending entries
    pending = [
        item
        for item in data
        if isinstance(item, dict)
        and item.get("status") == "pending"
        and isinstance(item.get("name"), str)
        and item["name"].strip()
    ]

    # Separate kana-only and web research candidates
    kana_only = []
    web_research = []
    
    for item in pending:
        name = item["name"].strip()
        if is_kana_only(name):
            kana_only.append(item)
        else:
            web_research.append(item)

    print(f"Total entries: {len(data)}")
    print(f"Pending entries: {len(pending)}")
    print(f"Kana-only automatic assignments: {len(kana_only)}")
    print(f"Web research candidates: {len(web_research)}")
    print(f"Skipped non-pending entries: {len(data) - len(pending)}")

    if not pending:
        print("No pending entries. Nothing to research.")
        return 0

    # Process kana-only names
    print()
    print("=" * 60)
    print("Processing kana-only names...")
    print("=" * 60)

    for index, item in enumerate(kana_only, start=1):
        name = item["name"].strip()
        print(f"[{index}/{len(kana_only)}] Kana-only: {name}")
        process_kana_only(item)

    # Process web research candidates
    print()
    print("=" * 60)
    print("Processing web research candidates...")
    print("=" * 60)

    failures = []

    for index, item in enumerate(web_research, start=1):
        name = item["name"].strip()

        print()
        print("=" * 60)
        print(f"[{index}/{len(web_research)}] Web research: {name}")
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

        if index < len(web_research):
            print(f"Waiting {WAIT_SECONDS} seconds before the next request...")
            time.sleep(WAIT_SECONDS)

    # Save updated data
    try:
        with SAMPLE_PATH.open("w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"ERROR: failed to save {SAMPLE_PATH}: {e}", file=sys.stderr)
        return 1

    print()
    print("=" * 60)
    print("Batch research finished.")
    print(f"Kana-only processed: {len(kana_only)}")
    print(f"Web research successful: {len(web_research) - len(failures)}")
    print(f"Web research failed: {len(failures)}")

    if failures:
        print("Failed VTubers:")
        for name in failures:
            print(f"- {name}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
