from __future__ import annotations

import json
import os
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

ROOT = Path(__file__).resolve().parents[1]
WORK_ROOT = ROOT / "work"
NORMALIZED_ROOT = ROOT / "normalized"

RESULT_DIRS = ("input", "ok", "ng", "used", "error")


@dataclass(frozen=True)
class BatchItem:
    path: Path
    start: int
    end: int
    records: list[dict[str, Any]]


def processor_dir(name: str) -> Path:
    return WORK_ROOT / name


def ensure_processor_dirs(name: str) -> None:
    for directory in RESULT_DIRS:
        (processor_dir(name) / directory).mkdir(parents=True, exist_ok=True)


def read_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as f:
        data = json.load(f)
    validate_document(data, path)
    return data


def write_json(path: Path, data: dict[str, Any]) -> None:
    validate_document(data, path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    with tmp.open("w", encoding="utf-8", newline="\n") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.write("\n")
    os.replace(tmp, path)


def make_document(records: list[dict[str, Any]]) -> dict[str, Any]:
    return {"records": records}


def validate_record(record: Any, path: Path | None = None) -> None:
    if not isinstance(record, dict):
        raise ValueError(f"record must be an object: {path}")
    required = {"name", "reading", "previous_processor", "logs"}
    if set(record) != required:
        raise ValueError(f"record keys must be exactly {sorted(required)}: {path}")
    if not isinstance(record["name"], str):
        raise ValueError(f"record.name must be a string: {path}")
    if not isinstance(record["reading"], str):
        raise ValueError(f"record.reading must be a string: {path}")
    if not isinstance(record["previous_processor"], str):
        raise ValueError(f"record.previous_processor must be a string: {path}")
    if not isinstance(record["logs"], list):
        raise ValueError(f"record.logs must be an array: {path}")


def validate_document(data: Any, path: Path | None = None) -> None:
    if not isinstance(data, dict) or set(data) != {"records"}:
        raise ValueError(f"document must contain exactly the records key: {path}")
    if not isinstance(data["records"], list):
        raise ValueError(f"records must be an array: {path}")
    for record in data["records"]:
        validate_record(record, path)


def json_files(directory: Path) -> list[Path]:
    return sorted(p for p in directory.glob("*.json") if p.is_file())


def collect_batch(input_dir: Path, count: int) -> tuple[list[BatchItem], list[dict[str, Any]]]:
    if count <= 0:
        raise ValueError("count must be greater than zero")

    selected: list[BatchItem] = []
    collected: list[dict[str, Any]] = []
    remaining = count

    for path in json_files(input_dir):
        if remaining <= 0:
            break
        document = read_json(path)
        records = document["records"]
        take = min(len(records), remaining)
        if take == 0:
            continue
        selected.append(BatchItem(path, 0, take, records[:take]))
        collected.extend(records[:take])
        remaining -= take

    return selected, collected


def append_log(record: dict[str, Any], entry: Any) -> dict[str, Any]:
    result = dict(record)
    result["logs"] = list(record["logs"])
    result["logs"].append(entry)
    return result


def set_previous_processor(record: dict[str, Any], processor: str) -> dict[str, Any]:
    result = dict(record)
    result["previous_processor"] = processor
    return result


def stage_upstream_files(processor: str, upstream: str | None) -> None:
    """Move complete upstream batches into this processor's input directory."""
    ensure_processor_dirs(processor)
    destination = processor_dir(processor) / "input"
    source = NORMALIZED_ROOT / "vdb" if upstream is None else processor_dir(upstream) / "ng"
    if not source.exists():
        return
    for path in json_files(source):
        target = destination / path.name
        if target.exists():
            raise RuntimeError(f"input filename collision: {target}")
        shutil.move(str(path), str(target))


def plan_commit(
    processor: str,
    selected: list[BatchItem],
    outcomes: dict[str, list[dict[str, Any]]],
    batch_name: str,
) -> Callable[[], None]:
    """Prepare one complete batch and return the finalizing operation."""
    stage_root = processor_dir(processor) / ".transactions" / batch_name
    stage_root.mkdir(parents=True, exist_ok=False)
    input_dir = processor_dir(processor) / "input"

    try:
        for state, records in outcomes.items():
            if records:
                write_json(stage_root / state / f"{batch_name}.json", make_document(records))

        input_updates: list[tuple[Path, list[dict[str, Any]]]] = []
        for item in selected:
            original = read_json(item.path)["records"]
            input_updates.append((item.path, original[item.end:]))
    except Exception:
        shutil.rmtree(stage_root, ignore_errors=True)
        raise

    def commit() -> None:
        try:
            for state in outcomes:
                staged = stage_root / state / f"{batch_name}.json"
                if staged.exists():
                    os.replace(staged, processor_dir(processor) / state / staged.name)

            for path, remainder in input_updates:
                if remainder:
                    write_json(path, make_document(remainder))
                else:
                    path.unlink()
        finally:
            shutil.rmtree(stage_root, ignore_errors=True)

    return commit
