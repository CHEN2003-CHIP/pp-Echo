# experiment-report-skill

A reusable SKILL package for generating high-quality experiment reports from requirement documents and experiment data folders.

This package is designed for platforms that support skill-style workflows. It can also be used manually: read `SKILL.md`, then use the helper scripts in `scripts/` to scan inputs, analyze CSV files, parse logs, generate figures, and check report quality.

## What it does

Given files such as:

- experiment requirements: PDF, DOCX, Markdown, TXT, screenshots
- result data: CSV, XLSX, JSON, JSONL
- logs: TXT, LOG
- images: PNG, JPG
- source code
- compressed folders

It helps an agent produce:

- a structured experiment report
- data-driven figures and tables
- result analysis grounded in evidence
- quality checks before final delivery

## Recommended usage

```bash
python scripts/scan_inputs.py --input_dir examples/sample_input --output outputs/input_inventory.json
python scripts/analyze_csv.py --input_dir examples/sample_input --output_dir outputs/analysis --figures_dir outputs/figures
python scripts/parse_logs.py --input_dir examples/sample_input --output outputs/log_summary.json
python scripts/quality_check.py --report_md templates/report_outline_zh.md --inventory outputs/input_inventory.json
```

## Suggested folder layout for a real task

```text
input/
├── requirements/
│   └── experiment_requirement.pdf
├── data/
│   └── results.csv
├── logs/
│   └── run.log
├── images/
│   └── screenshot.png
└── code/
    └── main.py
```

## Dependencies for helper scripts

The scripts are intentionally lightweight.

Required:

```bash
pip install pandas matplotlib
```

Optional for future extension:

```bash
pip install python-docx openpyxl pillow
```

## Notes

The scripts do not replace the agent workflow. They provide structured intermediate evidence. The real report quality comes from combining:

1. requirement checklist
2. file inventory
3. data/statistical summaries
4. generated figures
5. evidence-based writing
6. final quality check
