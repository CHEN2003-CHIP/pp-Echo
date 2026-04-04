from __future__ import annotations

import argparse
import json
from pathlib import Path

from pp_agent.benchmarks.harness import run_suite


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def main() -> None:
    parser = argparse.ArgumentParser(description="Run deterministic pp-Echo benchmark suites.")
    parser.add_argument("--suite", default="core")
    parser.add_argument("--artifacts-dir", default=None)
    parser.add_argument("--docs-output", default=None)
    args = parser.parse_args()

    repo_root = _repo_root()
    artifacts_dir = Path(args.artifacts_dir) if args.artifacts_dir else repo_root / "artifacts" / "benchmarks"
    docs_output = Path(args.docs_output) if args.docs_output else repo_root / "docs" / "benchmarks" / "latest.md"

    result, artifact_path = run_suite(
        repo_root,
        suite=args.suite,
        artifacts_dir=artifacts_dir,
        docs_output=docs_output,
    )
    payload = {
        "suite": result.suite,
        "task_count": result.task_count,
        "artifact": str(artifact_path) if artifact_path is not None else None,
        "docs": str(docs_output),
        "aggregate_metrics": result.aggregate_metrics,
        "headline_results": result.headline_results,
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
