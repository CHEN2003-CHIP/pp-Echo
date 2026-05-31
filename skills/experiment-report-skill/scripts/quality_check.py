#!/usr/bin/env python3
"""Lightweight quality checker for generated experiment report drafts."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Dict, List

DEFAULT_REQUIRED_ZH = [
    "实验目的",
    "实验环境",
    "实验原理",
    "实验步骤",
    "实验结果",
    "分析",
    "总结",
]

DEFAULT_REQUIRED_EN = [
    "purpose",
    "environment",
    "principle",
    "procedure",
    "result",
    "analysis",
    "conclusion",
]

GENERIC_PHRASES = [
    "性能很好",
    "效果很好",
    "结果很好",
    "取得了良好的效果",
    "达到了预期效果",
    "significantly improves performance",
    "good performance",
]


def read_text(path: Path) -> str:
    for enc in ["utf-8", "utf-8-sig", "gbk", "latin-1"]:
        try:
            return path.read_text(encoding=enc, errors="replace")
        except Exception:
            continue
    return path.read_text(errors="replace")


def check_required_sections(text: str) -> List[str]:
    low = text.lower()
    missing_zh = [s for s in DEFAULT_REQUIRED_ZH if s not in text]
    missing_en = [s for s in DEFAULT_REQUIRED_EN if s not in low]

    # Accept either Chinese or English coverage. Return the shorter missing list.
    if len(missing_zh) <= len(missing_en):
        return [f"Missing or unclear Chinese section: {s}" for s in missing_zh]
    return [f"Missing or unclear English section: {s}" for s in missing_en]


def check_figures_and_tables(text: str) -> List[str]:
    issues: List[str] = []
    figure_titles = re.findall(r"图\s*\d+|Figure\s+\d+", text, flags=re.IGNORECASE)
    table_titles = re.findall(r"表\s*\d+|Table\s+\d+", text, flags=re.IGNORECASE)

    if not figure_titles and not table_titles:
        issues.append("No figure or table numbering detected. Confirm whether the requirement allows a text-only report.")

    # Very lightweight reference check.
    if figure_titles:
        unique = sorted(set(figure_titles))
        for title in unique:
            if text.count(title) < 1:
                issues.append(f"Figure marker appears malformed: {title}")
    return issues


def check_generic_language(text: str) -> List[str]:
    issues = []
    for phrase in GENERIC_PHRASES:
        if phrase.lower() in text.lower():
            issues.append(f"Generic claim found; add data evidence near phrase: {phrase}")
    return issues


def check_inventory_support(inventory_path: Path) -> List[str]:
    if not inventory_path or not inventory_path.exists():
        return ["Inventory file not found; cannot verify input coverage."]
    try:
        data = json.loads(inventory_path.read_text(encoding="utf-8"))
    except Exception as exc:
        return [f"Failed to read inventory: {exc}"]

    issues = []
    summary = data.get("summary_by_category", {})
    if not any(k in summary for k in ["data", "data_or_metadata"]):
        issues.append("No data files detected in inventory; result analysis may rely only on logs/images.")
    if not any(k in summary for k in ["requirements_or_document", "requirements_or_notes"]):
        issues.append("No explicit requirement document detected in inventory; report structure may be inferred.")
    return issues


def main() -> None:
    parser = argparse.ArgumentParser(description="Check an experiment report draft for common quality issues.")
    parser.add_argument("--report_md", required=True, help="Markdown report draft to check.")
    parser.add_argument("--inventory", required=False, help="Input inventory JSON from scan_inputs.py.")
    parser.add_argument("--output", required=False, help="Optional JSON output path.")
    args = parser.parse_args()

    report_path = Path(args.report_md).resolve()
    if not report_path.exists():
        raise SystemExit(f"Report draft not found: {report_path}")

    text = read_text(report_path)
    issues: List[str] = []
    issues.extend(check_required_sections(text))
    issues.extend(check_figures_and_tables(text))
    issues.extend(check_generic_language(text))
    if args.inventory:
        issues.extend(check_inventory_support(Path(args.inventory).resolve()))

    result: Dict = {
        "report": str(report_path),
        "issue_count": len(issues),
        "issues": issues,
    }

    if args.output:
        output = Path(args.output).resolve()
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"Wrote quality check result: {output}")

    if issues:
        print("Quality check issues:")
        for i, issue in enumerate(issues, 1):
            print(f"{i}. {issue}")
    else:
        print("Quality check passed: no common issues detected.")


if __name__ == "__main__":
    main()
