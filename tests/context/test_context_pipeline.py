from __future__ import annotations

import pytest

from pp_agent.context import (
    ContextBudgetExceeded,
    ContextItem,
    ContextPipeline,
    ContextPipelineConfig,
    SourceRef,
    build_context_built_event,
    read_workspace_memory,
)
from pp_agent.domain import ChatMessage


def _item(
    item_id: str,
    *,
    content: str = "content",
    priority: int = 0,
    item_type: str = "project_context",
    source_type: str = "project_map",
    estimated_chars: int = None,
) -> ContextItem:
    return ContextItem(
        id=item_id,
        type=item_type,  # type: ignore[arg-type]
        title=item_id,
        content=content,
        source_ref=SourceRef(source_type=source_type, source_id=item_id),  # type: ignore[arg-type]
        priority=priority,
        estimated_chars=estimated_chars,
    )


def test_context_pack_serializable() -> None:
    pipeline = ContextPipeline()

    pack = pipeline.build(
        user_message="hello",
        model_profile={"model_id": "fake-model", "context_window": 8000, "api_token": "hidden"},
        runtime_profile={"runtime_id": "local-runtime", "tools": 3},
        project_context_providers=[_item("project-map", content="project map preview")],
    )

    payload = pack.model_dump(mode="json")
    assert payload["model_profile_summary"][0]["title"] == "fake-model"
    assert "api_token" not in payload["model_profile_summary"][0]["content"]
    assert payload["budget_report"]["included_items"]


def test_budget_report_records_dropped_items() -> None:
    pipeline = ContextPipeline(
        ContextPipelineConfig(
            total_budget=20,
            section_budgets={"project_context": 10},
        )
    )

    pack = pipeline.build(
        user_message="hello",
        project_context_providers=[
            _item("keep", content="12345", priority=10),
            _item("drop", content="123456", priority=1),
        ],
    )

    assert [item.id for item in pack.project_context] == ["keep"]
    assert pack.budget_report.drop_reasons["drop"] == "section_budget_exceeded"
    assert pack.budget_report.dropped_items[0].id == "drop"


def test_context_pipeline_respects_section_budget() -> None:
    pipeline = ContextPipeline(
        ContextPipelineConfig(
            total_budget=50,
            section_budgets={"attachment_previews": 8},
        )
    )

    pack = pipeline.build(
        user_message="hello",
        attachment_providers=[
            _item("a", content="1234", priority=2, item_type="attachment_preview", source_type="attachment"),
            _item("b", content="5678", priority=1, item_type="attachment_preview", source_type="attachment"),
            _item("c", content="overflow", priority=0, item_type="attachment_preview", source_type="attachment"),
        ],
    )

    assert [item.id for item in pack.attachment_previews] == ["a", "b"]
    assert pack.budget_report.per_section["attachments"].used == 8
    assert pack.budget_report.drop_reasons["c"] == "section_budget_exceeded"


def test_source_ref_supports_attachment_page_line() -> None:
    source = SourceRef(
        source_type="attachment",
        source_id="att-1",
        path="docs/spec.pdf",
        page=2,
        line_start=10,
        line_end=12,
        heading="Budget",
        confidence=1.5,
    )

    assert source.page == 2
    assert source.line_start == 10
    assert source.line_end == 12
    assert source.confidence == 1.0
    assert source.summary()["path"] == "docs/spec.pdf"


def test_context_built_event_shape() -> None:
    pipeline = ContextPipeline()
    pack = pipeline.build(user_message="hello", project_context_providers=[_item("project")])

    event = build_context_built_event(pack, model_id="m1", runtime_id="r1")

    assert event["name"] == "context_built"
    assert event["attributes"]["model_id"] == "m1"  # type: ignore[index]
    assert event["attributes"]["runtime_id"] == "r1"  # type: ignore[index]
    assert "included_source_summaries" not in event["payload"]  # type: ignore[operator]
    assert event["payload"]["context_payload_version"] == 3  # type: ignore[index]
    assert "included_sources" in event["payload"]["context"]  # type: ignore[index]
    assert "dropped_sources" in event["payload"]["context"]  # type: ignore[index]
    assert "budget_report" in event["payload"]["context"]  # type: ignore[index]


def test_core_memory_not_silently_truncated() -> None:
    pipeline = ContextPipeline(
        ContextPipelineConfig(
            total_budget=20,
            section_budgets={"core_memory_snapshot": 5},
            debug_include_core_governance=True,
        )
    )

    with pytest.raises(ContextBudgetExceeded) as exc:
        pipeline.build(
            user_message="hello",
            memory_providers={
                "core_memory_snapshot": [
                    _item(
                        "core-too-large",
                        content="too large",
                        item_type="core_memory",
                        source_type="core_memory",
                    )
                ]
            },
        )

    assert exc.value.report.drop_reasons["core-too-large"] == "core_memory_budget_exceeded_not_truncated"


def test_context_pipeline_has_markdown_memory_section(tmp_path) -> None:
    (tmp_path / "MEMORY.md").write_text("# Project Memory\n\nUse focused tests.\n", encoding="utf-8")

    pack = ContextPipeline().build(user_message="hello", workspace=tmp_path)

    assert pack.markdown_memory
    assert pack.markdown_memory[0].type == "markdown_memory"
    assert pack.budget_report.included_items[0].section == "markdown_memory"
    assert not pack.project_context


def test_markdown_memory_source_ref_has_path_and_hash(tmp_path) -> None:
    (tmp_path / "MEMORY.md").write_text("# Project Memory\n\nFact.\n<!-- pp-memory:id=abc -->\n", encoding="utf-8")

    result = read_workspace_memory(tmp_path)

    assert result.item is not None
    ref = result.item.source_ref
    assert ref.source_type == "markdown_memory"
    assert ref.path == "MEMORY.md"
    assert ref.line_start == 1
    assert ref.metadata["content_hash"]
    assert ref.metadata["marker_ids"] == ["abc"]


def test_context_pipeline_reflects_approved_memory_next_turn(tmp_path) -> None:
    (tmp_path / "MEMORY.md").write_text("# Project Memory\n\nOld fact.\n", encoding="utf-8")
    first = ContextPipeline().build(user_message="hello", workspace=tmp_path)
    (tmp_path / "MEMORY.md").write_text("# Project Memory\n\nNew approved fact.\n", encoding="utf-8")

    second = ContextPipeline().build(user_message="hello", workspace=tmp_path)

    assert "Old fact." in first.markdown_memory[0].content
    assert "New approved fact." in second.markdown_memory[0].content


def test_core_governance_debug_only() -> None:
    core = _item("core", content="SQLite active memory", item_type="core_governance", source_type="core_governance")

    default_pack = ContextPipeline().build(user_message="hello", memory_providers={"core_governance": [core]}, strict_core_memory=False)
    debug_pack = ContextPipeline(ContextPipelineConfig(debug_include_core_governance=True)).build(
        user_message="hello",
        memory_providers={"core_governance": [core]},
        strict_core_memory=False,
    )

    assert not default_pack.core_governance
    assert default_pack.budget_report.drop_reasons["core"] == "core_memory_prompt_injection_disabled"
    assert debug_pack.core_governance[0].id == "core"


def test_context_pipeline_render_messages_feature_flag(tmp_path) -> None:
    (tmp_path / "MEMORY.md").write_text("# Project Memory\n\nRendered fact.\n", encoding="utf-8")

    pack = ContextPipeline(ContextPipelineConfig(use_context_pipeline_messages=True)).build(
        user_message="hello",
        workspace=tmp_path,
        system_instructions="system",
    )

    assert pack.final_messages
    assert all(isinstance(message, ChatMessage) for message in pack.final_messages)
    assert any(message.metadata.get("context_section") == "markdown_memory" for message in pack.final_messages)


def test_context_built_event_contains_markdown_memory(tmp_path) -> None:
    (tmp_path / "MEMORY.md").write_text("# Project Memory\n\nTraceable fact.\n", encoding="utf-8")
    pack = ContextPipeline().build(user_message="hello", workspace=tmp_path)

    event = build_context_built_event(pack)

    assert event["payload"]["context"]["markdown_memory"]["paths"] == ["MEMORY.md"]  # type: ignore[index]


def test_memory_md_not_misclassified_as_project_context(tmp_path) -> None:
    (tmp_path / "MEMORY.md").write_text("# Project Memory\n\nBootstrap memory.\n", encoding="utf-8")

    pack = ContextPipeline().build(user_message="hello", workspace=tmp_path)

    assert pack.markdown_memory
    assert not any(item.source_ref.path == "MEMORY.md" for item in pack.project_context)
