from __future__ import annotations

from pp_agent.subagents.specs import SubAgentRunResult, parse_subagent_output


def test_parse_subagent_output_reads_sectioned_summary() -> None:
    parsed = parse_subagent_output(
        "Summary\n"
        "- Quick repo scan\n\n"
        "Findings\n"
        "- Found runtime hook path\n"
        "- Found tool registry path\n\n"
        "Recommended next action\n"
        "- Update manager validation\n\n"
        "Files/paths inspected\n"
        "- src/pp_agent/runtime/runtime.py\n"
        "- src/pp_agent/tools/registry.py\n\n"
        "Confidence\n"
        "- high\n"
    )

    assert parsed["summary"] == "Quick repo scan"
    assert parsed["findings"] == ["Found runtime hook path", "Found tool registry path"]
    assert parsed["recommended_next_action"] == "Update manager validation"
    assert parsed["inspected_paths"] == ["src/pp_agent/runtime/runtime.py", "src/pp_agent/tools/registry.py"]
    assert parsed["confidence"] == "high"


def test_parse_subagent_output_accepts_numbered_section_headings() -> None:
    parsed = parse_subagent_output(
        "0. Summary\n"
        "- Quick repo scan\n\n"
        "1. Findings\n"
        "- Found runtime hook path\n\n"
        "2. Recommended next action\n"
        "- Update manager validation\n\n"
        "3. Files/paths inspected\n"
        "- src/pp_agent/runtime/runtime.py\n\n"
        "4. Confidence\n"
        "- high\n"
    )

    assert parsed["summary"] == "Quick repo scan"
    assert parsed["findings"] == ["Found runtime hook path"]
    assert parsed["recommended_next_action"] == "Update manager validation"
    assert parsed["inspected_paths"] == ["src/pp_agent/runtime/runtime.py"]
    assert parsed["confidence"] == "high"


def test_subagent_run_result_renders_final_text_from_structured_fields() -> None:
    result = SubAgentRunResult(
        spec_name="repo-researcher",
        session_id="child-1",
        active_head_id="head-1",
        summary="Quick repo scan",
        findings=["Found runtime hook path"],
        recommended_next_action="Update manager validation",
        inspected_paths=["src/pp_agent/runtime/runtime.py"],
        confidence="high",
        event_count=3,
        success=True,
    )

    assert result.final_text.startswith("Findings")
    assert "Found runtime hook path" in result.final_text
    assert "Update manager validation" in result.final_text
