#!/usr/bin/env python3
"""
Generate the intermediate dictionary from source/vtuber-readings.json.

- Only include records with status == "verified".
- Require both 'reading' and 'name' to be non-empty.
- Keep only the fields needed by downstream IME converters: reading and name.
- Remove exact-duplicate (reading, name) pairs while preserving source order.
- Do not sort the entries.
- Do not modify source/vtuber-readings.json.
"""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RESULT_PATH = ROOT / "source" / "vtuber-readings.json"
OUT_DIR = ROOT / "source" / "intermediate"
OUT_FILE = OUT_DIR / "dictionary.json"


def load_results():
    with RESULT_PATH.open("r", encoding="utf-8") as f:
        return json.load(f)


def main():
    results = load_results()
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    seen = set()
    entries = []

    for rec in results:
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
        entries.append({
            "reading": reading,
            "name": name,
        })

    with OUT_FILE.open("w", encoding="utf-8", newline="\n") as f:
        json.dump(entries, f, ensure_ascii=False, indent=2)
        f.write("\n")

    print(f"Wrote {OUT_FILE} ({len(entries)} entries)")


if __name__ == "__main__":
    main()
