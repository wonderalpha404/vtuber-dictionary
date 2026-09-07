from __future__ import annotations

import re
from typing import Any

from .base import Outcome, Processor

KANA_ONLY_RE = re.compile(r"^[\u3040-\u309f\u30a0-\u30ff・ー]+$")


def kana_to_reading(name: str) -> str:
    result: list[str] = []
    for char in name:
        if char == "・":
            continue
        if "\u30a1" <= char <= "\u30f6":
            char = chr(ord(char) - 0x60)
        result.append(char)
    return "".join(result)


class KanaProcessor(Processor):
    name = "kana"
    upstream = None

    def process(self, record: dict[str, Any]) -> Outcome:
        name = record["name"]
        if not name or not KANA_ONLY_RE.fullmatch(name):
            return Outcome("ng", record)

        reading = kana_to_reading(name)
        if not reading:
            return Outcome("ng", record)

        result = dict(record)
        result["reading"] = reading
        return Outcome("ok", result)
