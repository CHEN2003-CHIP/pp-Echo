#!/usr/bin/env python3
"""Scan an experiment input folder and build a structured file inventory."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Dict, List


CATEGORY_BY_EXT = {
    ".pdf": "requirements_or_document",
    ".docx": "requirements_or_document",
    ".doc": "requirements_or_document",
    ".md": "requirements_or_notes",
    ".txt": "log_or_notes",
    ".log": "log_or_notes",
    ".csv": "data",
    ".tsv": "data",
    ".xlsx": "data",
    ".xls": "data",
    ".json": "data_or_metadata",
    ".jsonl": "data_or_metadata",
    ".png": "image",
    ".jpg": "image",
    ".jpeg": "image",
    ".webp": "image",
    ".svg": "image_or_diagram",
    ".drawio": "editable_diagram",
    ".py": "source_code",
    ".ipynb": "source_code",
    ".c": "source_code",
    ".cc": "source_code",
    ".cpp": "source_code",
    ".cu": "source_code",
    ".h": "source_code",
    ".hpp": "source_code",
    ".java": "source_code",
    ".js": "source_code",
    ".ts": "source_code",
    ".zip": "archive",
    ".tar": "archive",
    ".gz": "archive",
    ".7z": "archive",
}


def sha256_short(path: Path, chunk_size: int = 1024 * 1024) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        while True:
            chunk = f.read(chunk_size)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()[:16]


def likely_role(path: Path, category: str) -> str:
    name = path.name.lower()
    parent = str(path.parent).lower()
    combined = f"{parent}/{name}"

    if category.startswith("requirements") or "requirement" in combined or "实验要求" in combined:
        return "experiment requirement or report instruction"
    if category == "data":
        return "result data for tables, statistics, or figures"
    if category == "log_or_notes":
        if any(k in combined for k in ["log", "run", "terminal", "output"]):
            return "execution log, command record, or terminal output"
        return "notes or auxiliary text"
    if category.startswith("image"):
        return "existing figure, screenshot, or visual evidence"
    if category == "source_code":
        return "implementation evidence or algorithm reference"
    if category == "editable_diagram":
        return "editable diagram source"
    if category == "archive":
        return "compressed input archive; extract before detailed analysis"
    return "auxiliary file"


def scan(input_dir: Path) -> Dict:
    files: List[Dict] = []
    for path in sorted(input_dir.rglob("*")):
        if not path.is_file():
            continue
        ext = path.suffix.lower()
        category = CATEGORY_BY_EXT.get(ext, "unknown")
        try:
            size_bytes = path.stat().st_size
        except OSError:
            size_bytes = None
        record = {
            "relative_path": str(path.relative_to(input_dir)),
            "name": path.name,
            "extension": ext,
            "category": category,
            "likely_role": likely_role(path, category),
            "size_bytes": size_bytes,
        }
        if size_bytes is not None and size_bytes <= 20 * 1024 * 1024:
            try:
                record["sha256_short"] = sha256_short(path)
            except OSError:
                record["sha256_short"] = None
        files.append(record)

    summary: Dict[str, int] = {}
    for item in files:
        summary[item["category"]] = summary.get(item["category"], 0) + 1

    return {
        "input_dir": str(input_dir),
        "total_files": len(files),
        "summary_by_category": summary,
        "files": files,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Scan experiment input files and generate an inventory JSON.")
    parser.add_argument("--input_dir", required=True, help="Input folder containing experiment materials.")
    parser.add_argument("--output", required=True, help="Output inventory JSON path.")
    args = parser.parse_args()

    input_dir = Path(args.input_dir).resolve()
    output = Path(args.output).resolve()
    if not input_dir.exists() or not input_dir.is_dir():
        raise SystemExit(f"Input directory does not exist or is not a directory: {input_dir}")

    output.parent.mkdir(parents=True, exist_ok=True)
    inventory = scan(input_dir)
    output.write_text(json.dumps(inventory, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Wrote inventory: {output}")
    print(json.dumps(inventory["summary_by_category"], ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
