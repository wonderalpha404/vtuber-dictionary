from __future__ import annotations

import json
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "source" / "vdb.json"
OUTPUT = ROOT / "normalized" / "vdb" / "vdb.json"


def normalize() -> int:
    with SOURCE.open("r", encoding="utf-8") as f:
        data = json.load(f)

    vtbs = data.get("vtbs")
    if not isinstance(vtbs, list):
        raise ValueError("source/vdb.json: vtbs must be an array")

    records = []
    for item in vtbs:
        if not isinstance(item, dict) or item.get("type") != "vtuber":
            continue
        names = item.get("name")
        if not isinstance(names, dict):
            continue
        name = names.get("jp")
        if not isinstance(name, str) or not name:
            continue
        records.append(
            {
                "name": name,
                "reading": "",
                "previous_processor": "",
                "logs": [{"processor": "normalize_vdb", "result": "ok"}],
            }
        )

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    tmp = OUTPUT.with_name(OUTPUT.name + ".tmp")
    with tmp.open("w", encoding="utf-8", newline="\n") as f:
        json.dump({"records": records}, f, ensure_ascii=False, indent=2)
        f.write("\n")
    os.replace(tmp, OUTPUT)
    print(f"normalized={len(records)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(normalize())
