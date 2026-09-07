#!/usr/bin/env python3
"""
Generate IME dictionary from source/sample-10-jp.json.

- Only include records with status == "verified" AND both 'reading' and 'name' non-empty.
- Output file: ime/dictionary.tsv (tab-separated: reading<TAB>name), UTF-8 no BOM.
- Do NOT normalize name or reading.
- Do not call any external APIs.
- Remove exact-duplicate (reading, name) pairs while preserving the original order as much as possible.
"""
import json
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SAMPLE_PATH = ROOT / "source" / "sample-10-jp.json"
OUT_DIR = ROOT / "ime"
OUT_FILE = OUT_DIR / "dictionary.tsv"


def load_sample():
    with SAMPLE_PATH.open("r", encoding="utf-8") as f:
        return json.load(f)


def main():
    sample = load_sample()
    os.makedirs(OUT_DIR, exist_ok=True)
    seen = set()
    lines = []
    for rec in sample:
        if rec.get("status") != "verified":
            continue
        reading = (rec.get("reading") or "").strip()
        name = (rec.get("name") or "").strip()
        if not reading or not name:
            continue
        key = (reading, name)
        if key in seen:
            continue
        seen.add(key)
        lines.append(f"{reading}\t{name}")

    with OUT_FILE.open("w", encoding="utf-8") as f:
        for l in lines:
            f.write(l + "\n")

    print(f"Wrote {OUT_FILE} ({len(lines)} entries)")


if __name__ == "__main__":
    main()
