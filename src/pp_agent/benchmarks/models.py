from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel, Field


class BenchmarkTask(BaseModel):
    id: str
    group: str
    scenario: str
    title: str
    fixture: str = "repo"
    prompt: str = ""
    baseline_mode: str = "baseline"
    tags: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class ModeResult(BaseModel):
    mode: str
    success: bool
    metrics: dict[str, float] = Field(default_factory=dict)
    details: dict[str, Any] = Field(default_factory=dict)


class BenchmarkTaskResult(BaseModel):
    task_id: str
    group: str
    title: str
    modes: list[ModeResult] = Field(default_factory=list)


class BenchmarkSuiteResult(BaseModel):
    suite: str
    generated_at: str
    task_count: int
    fixture_root: str
    results: list[BenchmarkTaskResult] = Field(default_factory=list)
    aggregate_metrics: dict[str, float] = Field(default_factory=dict)
    headline_results: list[str] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)

    def mode_metrics(self, metric_name: str, mode: str) -> list[float]:
        values: list[float] = []
        for task in self.results:
            for item in task.modes:
                if item.mode != mode:
                    continue
                if metric_name in item.metrics:
                    values.append(float(item.metrics[metric_name]))
        return values

    def mode_result(self, task_id: str, mode: str) -> Optional[ModeResult]:
        for task in self.results:
            if task.task_id != task_id:
                continue
            for item in task.modes:
                if item.mode == mode:
                    return item
        return None
