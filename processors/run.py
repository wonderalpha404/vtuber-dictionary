from __future__ import annotations

import argparse
import importlib
from datetime import datetime, timezone
from typing import Type

from .base import Processor
from .common import (
    append_log,
    collect_batch,
    ensure_processor_dirs,
    plan_commit,
    processor_dir,
    set_previous_processor,
    stage_upstream_files,
)

PROCESSORS: dict[str, str] = {
    "kana": "processors.kana:KanaProcessor",
}


def load_processor(name: str) -> Processor:
    target = PROCESSORS.get(name)
    if target is None:
        raise ValueError(f"unknown processor: {name}")
    module_name, class_name = target.split(":", 1)
    cls: Type[Processor] = getattr(importlib.import_module(module_name), class_name)
    return cls()


def batch_name() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--processor", required=True)
    parser.add_argument("--count", required=True, type=int)
    args = parser.parse_args()

    processor = load_processor(args.processor)
    ensure_processor_dirs(processor.name)
    stage_upstream_files(processor.name, processor.upstream)

    selected, records = collect_batch(processor_dir(processor.name) / "input", args.count)
    if not records:
        print("No input records; normal completion.")
        return 0

    outcomes = {"ok": [], "ng": [], "error": []}
    for record in records:
        try:
            outcome = processor.process(record)
            if outcome.state not in outcomes:
                raise ValueError(f"invalid processor outcome: {outcome.state}")
            result = set_previous_processor(outcome.record, processor.name)
            result = append_log(result, {"processor": processor.name, "result": outcome.state})
            outcomes[outcome.state].append(result)
        except Exception as exc:
            result = set_previous_processor(record, processor.name)
            result = append_log(result, {"processor": processor.name, "result": "error", "message": str(exc)})
            outcomes["error"].append(result)

    commit = plan_commit(processor.name, selected, outcomes, batch_name())
    commit()

    print(
        f"processor={processor.name} processed={len(records)} "
        f"ok={len(outcomes['ok'])} ng={len(outcomes['ng'])} error={len(outcomes['error'])}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
