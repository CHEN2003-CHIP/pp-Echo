from __future__ import annotations

from pp_agent.tools.subagent_tool import _render_orchestration_content


def test_orchestration_content_includes_child_diagnostics() -> None:
    rendered = _render_orchestration_content(
        {
            "success": False,
            "workflow": "research",
            "final_summary": "failed",
            "recommended_next_action": "Use grep_code or list_files first.",
            "steps": [
                {
                    "agent": "repo-researcher",
                    "status": "failed",
                    "summary": "Invalid summary",
                    "session_id": "child-1",
                    "failure_kind": "invalid_summary",
                    "parse_error": True,
                }
            ],
        }
    )

    assert "repo-researcher [failed/invalid_summary]" in rendered
    assert "child session: child-1" in rendered
    assert "parse_error" in rendered
