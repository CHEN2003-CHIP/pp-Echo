# Experiment Report Skill

## Purpose

Use this skill when the user provides an experiment requirement document and a folder or archive containing experiment materials, such as CSV files, logs, screenshots, figures, source code, or notes, and asks for a high-quality experiment report.

The goal is to produce a report that is complete, evidence-based, clearly formatted, and suitable for academic or engineering submission.

Typical outputs:

- `experiment_report.docx`
- optional `experiment_report.pdf`
- `figures/` containing generated or selected report figures
- `analysis/` containing extracted summaries and intermediate tables
- optional editable diagrams, such as `.drawio`, when the experiment requires diagrams

## Core Principles

1. Treat the experiment requirement document as the highest-priority contract.
2. Do not invent experiment data, commands, environment information, or results.
3. Every conclusion should be supported by data, logs, screenshots, code, or requirement text.
4. Prefer data-driven analysis over generic writing.
5. Generate figures only when they help explain results.
6. Use concise, clear language. Avoid empty praise such as “the result is good” without evidence.
7. If required information is missing, state the limitation and complete the report using available evidence.
8. Always run a quality check before returning final artifacts.

## Inputs

The user may provide one or more of the following:

- experiment requirement document: PDF, DOCX, Markdown, text, screenshots
- data files: CSV, XLSX, JSON, JSONL
- logs: TXT, LOG, terminal output
- images: PNG, JPG, JPEG, WEBP
- source code: C/C++, Python, CUDA, Java, etc.
- compressed archive: ZIP, TAR, TAR.GZ, 7Z
- additional instructions: page size, language, style, required sections, whether to include appendix

## Required Workflow

### Step 1: Build an input inventory

Inspect all uploaded files and classify them into:

- requirements
- data
- logs
- figures/images
- source code
- existing documents
- unknown or auxiliary files

For each file, record:

- file name
- file type
- relative path
- likely role in the report
- whether it should be cited, summarized, plotted, or inserted

Recommended helper script:

```bash
python scripts/scan_inputs.py --input_dir <input_folder> --output analysis/input_inventory.json
```

### Step 2: Parse experiment requirements

Extract a checklist from the requirement document.

The checklist should include:

- required report sections
- required experiment tasks
- required figures/tables
- required performance metrics
- required analysis questions
- formatting requirements
- submission requirements
- bonus or optional tasks

If the requirement document is a PDF or image-based file, inspect visual pages when necessary. Do not rely only on partial text extraction if figures, tables, or layout contain important requirements.

Output an internal checklist similar to:

```text
[ ] Experiment purpose
[ ] Experiment environment
[ ] Experiment principle or algorithm
[ ] Experiment steps
[ ] Baseline result
[ ] Optimized result
[ ] Figure comparing runtime
[ ] Table summarizing speedup
[ ] Analysis of performance trend
[ ] Conclusion and limitations
```

### Step 3: Parse data and logs

For CSV/XLSX files:

- identify columns
- infer experiment variables, such as input size, method, repeat count, runtime, throughput, accuracy, speedup
- calculate useful statistics, such as average, min, max, standard deviation, and speedup
- detect whether multiple files belong to the same experiment

Recommended helper script:

```bash
python scripts/analyze_csv.py --input_dir <input_folder> --output_dir analysis --figures_dir figures
```

For TXT/LOG files:

- extract commands
- extract parameters
- extract environment information
- extract warnings or errors
- extract final metric lines

Recommended helper script:

```bash
python scripts/parse_logs.py --input_dir <input_folder> --output analysis/log_summary.json
```

### Step 4: Decide which figures and tables to use

Use these rules:

- If there are multiple methods, create a comparison figure or table.
- If there are multiple input sizes, create a size-vs-metric figure.
- If there are repeated runs, report average and optionally standard deviation.
- If both baseline and optimized results exist, compute speedup when possible.
- If existing images are unclear but source data is available, regenerate clean figures.
- If an image is a terminal screenshot or result screenshot, insert it only when it provides evidence not already captured by data tables.

Common figure types:

- runtime comparison
- speedup comparison
- throughput comparison
- accuracy or loss curve
- memory usage curve
- ablation comparison
- stability across repeated runs

### Step 5: Build the report outline

Use the requirement document first. If no fixed outline is given, use this default structure:

```text
1. Experiment Purpose
2. Experiment Environment
3. Experiment Principle
4. Experiment Design
5. Experiment Procedure
6. Experiment Results and Analysis
7. Problems and Improvements
8. Conclusion
9. Appendix, optional
```

For Chinese academic reports, the default structure can be:

```text
1 实验目的
2 实验环境
3 实验原理
4 实验设计
5 实验步骤
6 实验结果与分析
7 问题与改进
8 实验总结
```

### Step 6: Write evidence-based analysis

Avoid generic statements.

Poor:

```text
The optimized method performs well.
```

Better:

```text
According to Table 2 and Figure 3, the optimized method reduces average runtime as the input scale increases. This indicates that the optimization is more effective when the computation workload is large enough to amortize overhead.
```

Every result subsection should follow this pattern:

1. State what was measured.
2. Present table or figure.
3. Describe the trend.
4. Explain why the trend appears.
5. Connect the result back to the experiment goal.

### Step 7: Format the report

Unless the user or requirement document says otherwise:

- page size: A4
- orientation: portrait
- title: centered
- headings: numbered
- body paragraphs: clear spacing, first-line indentation for Chinese reports
- tables: table title above the table
- figures: figure title below the figure
- figures and tables should be referenced in the text
- avoid distorted images
- avoid large blank areas

### Step 8: Run quality checks

Before final delivery, check:

- all required sections are present
- all required tasks are covered
- all figures and tables are numbered
- all figures and tables are referenced in the text
- data-derived claims match actual data
- no fabricated metrics exist
- missing information is explicitly marked
- formatting is consistent
- final files open correctly

Recommended helper script:

```bash
python scripts/quality_check.py --report_md <report.md> --inventory analysis/input_inventory.json
```

## Tool Use Guidelines

- Use spreadsheet/data tools for CSV/XLSX analysis.
- Use document-generation tools for DOCX creation.
- Use PDF tools when the requirement document is PDF.
- Use screenshot or visual inspection when PDF pages contain diagrams, tables, or scanned content.
- Use Python or equivalent tools to generate clean plots from CSV data.
- Do not use OCR unless visual reading is not enough.

## Handling Missing Information

If important information is missing, do not stop unless the missing item makes the report impossible.

Use transparent wording:

```text
The provided files do not contain explicit hardware information. Therefore, this report records the environment based on the visible command output and marks the remaining environment items as not provided.
```

If a section is required but no evidence exists, include a short placeholder-style explanation rather than fabricating details.

## Output Contract

Return a concise summary with links to artifacts:

- final report
- generated figures
- editable diagrams, if any
- analysis files, if useful
- notes about missing or inferred information

Example final response:

```text
已生成实验报告和配套图表：

- 实验报告：experiment_report.docx
- 数据分析结果：analysis_summary.json
- 图表目录：figures/

说明：报告已覆盖实验要求中的基础实验和附加实验。实验环境中缺少显卡型号，因此已在报告中标记为“未提供”。
```
