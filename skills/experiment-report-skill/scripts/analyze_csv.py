#!/usr/bin/env python3
"""Analyze CSV/XLSX result files and generate simple report-ready summaries and figures."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import pandas as pd

try:
    import matplotlib.pyplot as plt
except Exception as exc:  # pragma: no cover
    plt = None
    MATPLOTLIB_IMPORT_ERROR = exc
else:
    MATPLOTLIB_IMPORT_ERROR = None


NUMERIC_HINTS = [
    "time", "runtime", "latency", "ms", "s", "sec", "seconds",
    "throughput", "tflops", "gflops", "speedup", "acc", "accuracy",
    "loss", "memory", "bandwidth", "gbps", "mbps",
]
GROUP_HINTS = ["method", "algo", "algorithm", "version", "impl", "mode", "type", "name", "kernel"]
SIZE_HINTS = ["size", "n", "m", "k", "batch", "seq", "length", "scale"]


def read_table(path: Path) -> Optional[pd.DataFrame]:
    try:
        if path.suffix.lower() in {".xlsx", ".xls"}:
            return pd.read_excel(path)
        if path.suffix.lower() == ".tsv":
            return pd.read_csv(path, sep="\t")
        return pd.read_csv(path)
    except Exception as exc:
        print(f"Warning: failed to read {path}: {exc}")
        return None


def safe_name(text: str) -> str:
    text = re.sub(r"[^a-zA-Z0-9_\-]+", "_", text.strip())
    return text.strip("_") or "unnamed"


def infer_columns(df: pd.DataFrame) -> Dict[str, List[str]]:
    numeric_cols = [c for c in df.columns if pd.api.types.is_numeric_dtype(df[c])]
    lower = {c: str(c).lower() for c in df.columns}

    metric_cols = [
        c for c in numeric_cols
        if any(hint in lower[c] for hint in NUMERIC_HINTS)
    ]
    if not metric_cols:
        metric_cols = numeric_cols[:]

    group_cols = [
        c for c in df.columns
        if not pd.api.types.is_numeric_dtype(df[c])
        and any(hint in lower[c] for hint in GROUP_HINTS)
    ]

    size_cols = [
        c for c in numeric_cols
        if any(hint == lower[c] or hint in lower[c] for hint in SIZE_HINTS)
    ]

    return {
        "numeric_cols": [str(c) for c in numeric_cols],
        "metric_cols": [str(c) for c in metric_cols],
        "group_cols": [str(c) for c in group_cols],
        "size_cols": [str(c) for c in size_cols],
    }


def summarize_dataframe(df: pd.DataFrame) -> Dict:
    inferred = infer_columns(df)
    numeric_cols = inferred["numeric_cols"]
    summary: Dict = {
        "shape": [int(df.shape[0]), int(df.shape[1])],
        "columns": [str(c) for c in df.columns],
        "inferred_columns": inferred,
        "numeric_summary": {},
    }
    for col in numeric_cols:
        s = pd.to_numeric(df[col], errors="coerce").dropna()
        if s.empty:
            continue
        summary["numeric_summary"][col] = {
            "count": int(s.count()),
            "mean": float(s.mean()),
            "min": float(s.min()),
            "max": float(s.max()),
            "std": float(s.std()) if s.count() > 1 else 0.0,
        }
    return summary


def choose_plot_columns(df: pd.DataFrame, inferred: Dict[str, List[str]]) -> Optional[Tuple[str, str, Optional[str]]]:
    metric_cols = inferred["metric_cols"]
    size_cols = inferred["size_cols"]
    group_cols = inferred["group_cols"]
    numeric_cols = inferred["numeric_cols"]

    y_col = metric_cols[0] if metric_cols else (numeric_cols[-1] if numeric_cols else None)
    if y_col is None:
        return None

    x_col = None
    for col in size_cols:
        if col != y_col:
            x_col = col
            break
    if x_col is None:
        for col in numeric_cols:
            if col != y_col:
                x_col = col
                break
    if x_col is None:
        return None

    group_col = group_cols[0] if group_cols else None
    return x_col, y_col, group_col


def generate_plot(df: pd.DataFrame, source_name: str, figures_dir: Path) -> Optional[str]:
    if plt is None:
        print(f"Warning: matplotlib unavailable: {MATPLOTLIB_IMPORT_ERROR}")
        return None

    inferred = infer_columns(df)
    choice = choose_plot_columns(df, inferred)
    if choice is None:
        return None

    x_col, y_col, group_col = choice
    plot_df = df.copy()
    plot_df[x_col] = pd.to_numeric(plot_df[x_col], errors="coerce")
    plot_df[y_col] = pd.to_numeric(plot_df[y_col], errors="coerce")
    plot_df = plot_df.dropna(subset=[x_col, y_col])
    if plot_df.empty:
        return None

    figures_dir.mkdir(parents=True, exist_ok=True)
    output_path = figures_dir / f"fig_{safe_name(Path(source_name).stem)}_{safe_name(y_col)}.png"

    plt.figure(figsize=(7, 4.5))
    if group_col and group_col in plot_df.columns:
        for key, g in plot_df.groupby(group_col):
            g = g.sort_values(x_col)
            plt.plot(g[x_col], g[y_col], marker="o", label=str(key))
        plt.legend()
    else:
        plot_df = plot_df.sort_values(x_col)
        plt.plot(plot_df[x_col], plot_df[y_col], marker="o")
    plt.xlabel(str(x_col))
    plt.ylabel(str(y_col))
    plt.title(f"{Path(source_name).stem}: {y_col} vs {x_col}")
    plt.tight_layout()
    plt.savefig(output_path, dpi=200)
    plt.close()
    return str(output_path)


def analyze(input_dir: Path, output_dir: Path, figures_dir: Path) -> Dict:
    table_paths = []
    for ext in ["*.csv", "*.tsv", "*.xlsx", "*.xls"]:
        table_paths.extend(input_dir.rglob(ext))

    results: List[Dict] = []
    for path in sorted(table_paths):
        df = read_table(path)
        if df is None:
            continue
        summary = summarize_dataframe(df)
        rel = str(path.relative_to(input_dir))
        summary["relative_path"] = rel
        summary["generated_figure"] = generate_plot(df, rel, figures_dir)

        csv_summary_path = output_dir / f"summary_{safe_name(path.stem)}.csv"
        output_dir.mkdir(parents=True, exist_ok=True)
        try:
            df.describe(include="all").transpose().to_csv(csv_summary_path)
            summary["describe_csv"] = str(csv_summary_path)
        except Exception as exc:
            summary["describe_csv_error"] = str(exc)
        results.append(summary)

    return {
        "input_dir": str(input_dir),
        "table_file_count": len(results),
        "tables": results,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Analyze CSV/XLSX experiment result files.")
    parser.add_argument("--input_dir", required=True)
    parser.add_argument("--output_dir", required=True)
    parser.add_argument("--figures_dir", required=True)
    args = parser.parse_args()

    input_dir = Path(args.input_dir).resolve()
    output_dir = Path(args.output_dir).resolve()
    figures_dir = Path(args.figures_dir).resolve()
    if not input_dir.exists() or not input_dir.is_dir():
        raise SystemExit(f"Input directory does not exist or is not a directory: {input_dir}")

    output_dir.mkdir(parents=True, exist_ok=True)
    result = analyze(input_dir, output_dir, figures_dir)
    output_path = output_dir / "csv_analysis_summary.json"
    output_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Wrote analysis summary: {output_path}")
    print(f"Generated figures directory: {figures_dir}")


if __name__ == "__main__":
    main()
