#!/usr/bin/env python3
"""Run the helper pipeline: inventory, CSV analysis, log parsing, and optional report check."""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path


SCRIPT_DIR = Path(__file__).resolve().parent


def run(cmd: list[str]) -> None:
    print("+", " ".join(cmd))
    subprocess.run(cmd, check=True)


def main() -> None:
    parser = argparse.ArgumentParser(description="Run experiment-report-skill helper pipeline.")
    parser.add_argument("--input_dir", required=True)
    parser.add_argument("--output_dir", required=True)
    parser.add_argument("--report_md", required=False, help="Optional report draft to quality-check.")
    args = parser.parse_args()

    input_dir = Path(args.input_dir).resolve()
    output_dir = Path(args.output_dir).resolve()
    analysis_dir = output_dir / "analysis"
    figures_dir = output_dir / "figures"
    output_dir.mkdir(parents=True, exist_ok=True)

    inventory_path = analysis_dir / "input_inventory.json"
    run([sys.executable, str(SCRIPT_DIR / "scan_inputs.py"), "--input_dir", str(input_dir), "--output", str(inventory_path)])
    run([sys.executable, str(SCRIPT_DIR / "analyze_csv.py"), "--input_dir", str(input_dir), "--output_dir", str(analysis_dir), "--figures_dir", str(figures_dir)])
    run([sys.executable, str(SCRIPT_DIR / "parse_logs.py"), "--input_dir", str(input_dir), "--output", str(analysis_dir / "log_summary.json")])

    if args.report_md:
        run([sys.executable, str(SCRIPT_DIR / "quality_check.py"), "--report_md", str(Path(args.report_md).resolve()), "--inventory", str(inventory_path), "--output", str(analysis_dir / "quality_check.json")])

    print(f"Pipeline completed. Output directory: {output_dir}")


if __name__ == "__main__":
    main()
