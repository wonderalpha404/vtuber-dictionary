#!/usr/bin/env python3
import json
from collections import Counter
from pathlib import Path

INPUT = Path("source/vtuber-readings.json")
OUTPUT = Path("vtuber-readings-stat.txt")

ALLOWED_STATUS = {"verified", "review", "pending"}
ALLOWED_CONFIDENCE = {"", "high", "medium", "review", "unknown"}


def main() -> None:
    with INPUT.open("r", encoding="utf-8") as f:
        data = json.load(f)

    if not isinstance(data, list):
        raise ValueError("vtuber-readings.json must contain a JSON array")

    total = len(data)
    status = Counter()
    confidence = Counter()
    invalid_status = Counter()
    invalid_confidence = Counter()

    reading_count = 0
    dictionary_success = 0

    for record in data:
        if not isinstance(record, dict):
            raise ValueError("Each record must be a JSON object")

        current_status = record.get("status", "")
        current_confidence = record.get("confidence", "")
        reading = record.get("reading", "")

        status[current_status] += 1
        confidence[current_confidence] += 1

        if current_status not in ALLOWED_STATUS:
            invalid_status[current_status] += 1
        if current_confidence not in ALLOWED_CONFIDENCE:
            invalid_confidence[current_confidence] += 1

        if isinstance(reading, str) and reading != "":
            reading_count += 1

        # A verified result is considered dictionary-suitable regardless
        # of confidence. This includes deterministic results with confidence="".
        if current_status == "verified":
            dictionary_success += 1

    dictionary_not_success = total - dictionary_success
    success_rate = (dictionary_success / total * 100) if total else 0.0

    lines = [
        "VTuber Reading Statistics",
        "==========================",
        "",
        f"Total: {total}",
        "",
        "Status:",
        f"  verified: {status['verified']}",
        f"  review:   {status['review']}",
        f"  pending:  {status['pending']}",
        "",
        "Reading:",
        f"  with reading:    {reading_count}",
        f"  without reading: {total - reading_count}",
        "",
        "Dictionary:",
        f"  success:     {dictionary_success}",
        f"  not success: {dictionary_not_success}",
        f"  success rate: {success_rate:.2f}%",
        "",
        "Confidence:",
        f"  high:    {confidence['high']}",
        f"  medium:  {confidence['medium']}",
        f"  review:  {confidence['review']}",
        f"  unknown: {confidence['unknown']}",
        f"  empty:   {confidence['']}",
    ]

    if invalid_status:
        lines.extend(["", "INVALID STATUS:"])
        for value, count in sorted(invalid_status.items(), key=lambda x: str(x[0])):
            lines.append(f"  {value!r}: {count}")

    if invalid_confidence:
        lines.extend(["", "INVALID CONFIDENCE:"])
        for value, count in sorted(invalid_confidence.items(), key=lambda x: str(x[0])):
            lines.append(f"  {value!r}: {count}")

    OUTPUT.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(OUTPUT.read_text(encoding="utf-8"), end="")


if __name__ == "__main__":
    main()
