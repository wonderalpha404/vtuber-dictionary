#!/usr/bin/env python3
"""
scripts/generate_ime_dictionary.py

Reads source/sample-10-jp.json (JSON array) and generates
source/ime-dictionary.txt containing lines in the format:

    reading<TAB>name

Only records that meet all of the following are included:
 - status == "verified"
 - reading is not an empty string
 - name is not an empty string

Duplicates where both reading and name are identical are removed.
If reading is the same but name differs, both entries are kept.

On success prints the number of matched records and number of output entries.
On error exits with a non-zero status code.

This script deliberately does not normalize or change reading/name values.
"""

from __future__ import annotations
import sys
import json
from typing import List, Tuple, Set

INPUT_PATH = "source/sample-10-jp.json"
OUTPUT_PATH = "source/ime-dictionary.txt"


def load_json(path: str):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def main() -> int:
    try:
        data = load_json(INPUT_PATH)
    except FileNotFoundError:
        print(f"Error: input file not found: {INPUT_PATH}", file=sys.stderr)
        return 1
    except json.JSONDecodeError as e:
        print(f"Error: failed to parse JSON: {e}", file=sys.stderr)
        return 1
    
    if not isinstance(data, list):
        print(f"Error: expected a JSON array in {INPUT_PATH}", file=sys.stderr)
        return 1

    matched_count = 0
    seen: Set[Tuple[str, str]] = set()
    output_lines: List[str] = []

    for i, item in enumerate(data):
        # Expecting item to be a dict with keys 'status', 'reading', 'name'
        if not isinstance(item, dict):
            # skip non-dict entries silently
            continue

        status = item.get("status")
        reading = item.get("reading")
        name = item.get("name")

        # Only include when status == "verified" and reading/name are non-empty strings
        if status != "verified":
            continue
        if not isinstance(reading, str) or reading == "":
            continue
        if not isinstance(name, str) or name == "":
            continue

        matched_count += 1

        pair = (reading, name)
        if pair in seen:
            continue
        seen.add(pair)
        # Do not modify reading or name
        output_lines.append(f"{reading}\t{name}")

    try:
        # Write output (UTF-8)
        with open(OUTPUT_PATH, "w", encoding="utf-8", newline="\n") as outf:
            for line in output_lines:
                outf.write(line + "\n")
    except Exception as e:
        print(f"Error: failed to write output file: {e}", file=sys.stderr)
        return 1

    # Print counts to stdout
    print(f"対象件数: {matched_count}, 出力件数: {len(output_lines)}")
    return 0


if __name__ == "__main__":
    rc = main()
    sys.exit(rc)
