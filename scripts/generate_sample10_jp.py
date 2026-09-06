#!/usr/bin/env python3

import json
import sys
import unicodedata
from pathlib import Path

INPUT_PATH = Path("source/vdb.json")
OUTPUT_PATH = Path("source/sample-10-jp.json")
MAX_ITEMS = 10


def get_display_name(entry):
    name = entry.get("name")

    if not isinstance(name, dict):
        return ""

    default_key = name.get("default")

    if isinstance(default_key, str):
        value = name.get(default_key)
        if isinstance(value, str) and value:
            return value

    for key in ("jp", "cn", "en"):
        value = name.get(key)
        if isinstance(value, str) and value:
            return value

    for value in name.values():
        if isinstance(value, str) and value:
            return value

    return ""


def has_japanese_script(text):
    for char in text:
        code = ord(char)
        if (
            0x3040 <= code <= 0x309F
            or 0x30A0 <= code <= 0x30FF
            or 0x3400 <= code <= 0x4DBF
            or 0x4E00 <= code <= 0x9FFF
        ):
            return True

    return False


def main():
    if not INPUT_PATH.exists():
        print(
            f"ERROR: input file not found: {INPUT_PATH}",
            file=sys.stderr,
        )
        return 1

    try:
        with INPUT_PATH.open("r", encoding="utf-8") as f:
            data = json.load(f)
    except json.JSONDecodeError as e:
        print(
            f"ERROR: invalid JSON in {INPUT_PATH}: {e}",
            file=sys.stderr,
        )
        return 2

    if not isinstance(data, dict):
        print(
            "ERROR: vdb.json top-level value is not an object.",
            file=sys.stderr,
        )
        return 3

    vtbs = data.get("vtbs")

    if not isinstance(vtbs, list):
        print(
            "ERROR: vdb.json does not contain a 'vtbs' array.",
            file=sys.stderr,
        )
        return 4

    selected = []
    seen_names = set()

    for entry in vtbs:
        if not isinstance(entry, dict):
            continue

        if entry.get("type") != "vtuber":
            continue

        if entry.get("bot") is True:
            continue

        name = get_display_name(entry)

        if not name:
            continue

        normalized = unicodedata.normalize("NFKC", name)

        if not has_japanese_script(normalized):
            continue

        if normalized in seen_names:
            continue

        seen_names.add(normalized)

        selected.append(
            {
                "uuid": entry.get("uuid", ""),
                "name": name,
                "reading": "",
                "source": "",
                "source_type": "",
                "confidence": "unknown",
                "status": "pending",
                "checked_at": "",
                "notes": "",
            }
        )

        if len(selected) == MAX_ITEMS:
            break

    if len(selected) != MAX_ITEMS:
        print(
            f"ERROR: only {len(selected)} eligible Japanese-script "
            f"VTuber entries were found; {MAX_ITEMS} are required.",
            file=sys.stderr,
        )
        return 5

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)

    with OUTPUT_PATH.open("w", encoding="utf-8") as f:
        json.dump(
            selected,
            f,
            ensure_ascii=False,
            indent=2,
        )
        f.write("\n")

    print(f"Successfully wrote {len(selected)} entries to {OUTPUT_PATH}")

    print("Selected VTubers:")
    for index, item in enumerate(selected, start=1):
        print(f"{index}. {item['name']}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
