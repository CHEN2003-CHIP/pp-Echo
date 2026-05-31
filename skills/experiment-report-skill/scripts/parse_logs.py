#!/usr/bin/env python3
"""Parse log/text files and extract commands, environment hints, errors, and metric-like lines."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Dict, List

COMMAND_PATTERNS = [
    re.compile(r"(^|\s)(python\s+[^\n]+)", re.IGNORECASE),
    re.compile(r"(^|\s)(./[^\s]+\s*[^\n]*)"),
    re.compile(r"(^|\s)(bash\s+[^\n]+)", re.IGNORECASE),
    re.compile(r"(^|\s)(cmake\s+[^\n]+)", re.IGNORECASE),
    re.compile(r"(^|\s)(make\s*[^\n]*)", re.IGNORECASE),
    re.compile(r"(^|\s)(nvcc\s+[^\n]+)", re.IGNORECASE),
]

ERROR_KEYWORDS = ["error", "failed", "exception", "traceback", "segmentation fault", "out of memory", "nan"]
ENV_KEYWORDS = ["cuda", "gpu", "cpu", "driver", "python", "torch", "pytorch", "gcc", "nvcc", "nvidia-smi", "os"]
METRIC_REGEX = re.compile(
    r"(?P<key>loss|accuracy|acc|time|runtime|latency|speedup|throughput|tflops|gflops|bandwidth|memory)"
    r"\s*[:=]\s*(?P<value>[-+]?\d*\.?\d+(?:[eE][-+]?\d+)?)",
    re.IGNORECASE,
)


def read_text(path: Path) -> str:
    for enc in ["utf-8", "utf-8-sig", "gbk", "latin-1"]:
        try:
            return path.read_text(encoding=enc, errors="replace")
        except Exception:
            continue
    return path.read_text(errors="replace")


def extract_commands(text: str) -> List[str]:
    commands: List[str] = []
    for line in text.splitlines():
        line_clean = line.strip()
        if not line_clean:
            continue
        if line_clean.startswith("$"):
            commands.append(line_clean.lstrip("$ ").strip())
            continue
        for pattern in COMMAND_PATTERNS:
            m = pattern.search(line_clean)
            if m:
                commands.append(m.group(2).strip())
                break
    return list(dict.fromkeys(commands))[:50]


def extract_errors(text: str) -> List[str]:
    errors: List[str] = []
    for line in text.splitlines():
        low = line.lower()
        if any(k in low for k in ERROR_KEYWORDS):
            errors.append(line.strip())
    return errors[:100]


def extract_environment_hints(text: str) -> List[str]:
    hints: List[str] = []
    for line in text.splitlines():
        low = line.lower()
        if any(k in low for k in ENV_KEYWORDS):
            hints.append(line.strip())
    return hints[:100]


def extract_metrics(text: str) -> List[Dict[str, str]]:
    metrics: List[Dict[str, str]] = []
    for line in text.splitlines():
        for m in METRIC_REGEX.finditer(line):
            metrics.append({"key": m.group("key"), "value": m.group("value"), "line": line.strip()})
    return metrics[:200]


def parse_logs(input_dir: Path) -> Dict:
    paths = []
    for ext in ["*.log", "*.txt", "*.out", "*.err"]:
        paths.extend(input_dir.rglob(ext))

    files: List[Dict] = []
    for path in sorted(paths):
        text = read_text(path)
        rel = str(path.relative_to(input_dir))
        files.append({
            "relative_path": rel,
            "line_count": len(text.splitlines()),
            "commands": extract_commands(text),
            "environment_hints": extract_environment_hints(text),
            "errors_or_warnings": extract_errors(text),
            "metric_like_lines": extract_metrics(text),
            "tail_preview": "\n".join(text.splitlines()[-20:]),
        })
    return {
        "input_dir": str(input_dir),
        "log_file_count": len(files),
        "files": files,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Parse experiment logs and text outputs.")
    parser.add_argument("--input_dir", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    input_dir = Path(args.input_dir).resolve()
    output = Path(args.output).resolve()
    if not input_dir.exists() or not input_dir.is_dir():
        raise SystemExit(f"Input directory does not exist or is not a directory: {input_dir}")

    output.parent.mkdir(parents=True, exist_ok=True)
    result = parse_logs(input_dir)
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Wrote log summary: {output}")


if __name__ == "__main__":
    main()
