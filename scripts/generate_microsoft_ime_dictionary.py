#!/usr/bin/env python3
"""
Generate a Microsoft IME user dictionary text file from the intermediate dictionary.

Input:
    source/intermediate/dictionary.json

Output:
    ime/microsoft-ime/dictionary.txt

Microsoft IME text dictionary format:
    reading<TAB>word<TAB>part of speech

The output is UTF-16 with BOM and CRLF line endings, suitable for
Microsoft IME's "Text file import" function.
"""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
INPUT_PATH = ROOT / "source" / "intermediate" / "dictionary.json"
OUT_DIR = ROOT / "ime" / "microsoft-ime"
OUT_FILE = OUT_DIR / "dictionary.txt"

# VTuber names are proper names, so register them as proper nouns.
PART_OF_SPEECH = "固有名詞"


def load_intermediate_dictionary():
    with INPUT_PATH.open("r", encoding="utf-8") as f:
        data = json.load(f)

    if not isinstance(data, list):
        raise ValueError("Intermediate dictionary must be a JSON array")

    return data


def main():
    entries = load_intermediate_dictionary()
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    lines = []
    for entry in entries:
        if not isinstance(entry, dict):
            raise ValueError("Each intermediate dictionary entry must be an object")

        reading = (entry.get("reading") or "").strip()
        name = (entry.get("name") or "").strip()

        if not reading or not name:
            continue

        if "\t" in reading or "\r" in reading or "\n" in reading:
            raise ValueError(f"Invalid reading contains a tab/newline: {reading!r}")
        if "\t" in name or "\r" in name or "\n" in name:
            raise ValueError(f"Invalid name contains a tab/newline: {name!r}")

        lines.append(f"{reading}\t{name}\t{PART_OF_SPEECH}")

    # Microsoft IME accepts the exported/imported text dictionary as UTF-16
    # with a BOM and CRLF line endings.
    with OUT_FILE.open("w", encoding="utf-16", newline="\r\n") as f:
        for line in lines:
            f.write(line + "\n")

    print(f"Wrote {OUT_FILE} ({len(lines)} entries)")


if __name__ == "__main__":
    main()
