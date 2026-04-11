from __future__ import annotations

import json
from pathlib import Path

from pp_agent.app.bootstrap import create_tool_registry
from pp_agent.cli.commands.approvals import approve_or_execute_pending_action


def _write_extension(root: Path) -> None:
    root.mkdir(parents=True, exist_ok=True)
    (root / "EXTENSION.json").write_text(
        json.dumps(
            {
                "name": "demo_dynamic",
                "description": "Dynamic approval test extension",
                "entrypoint": "extension.py",
                "provides": ["tools"],
            }
        ),
        encoding="utf-8",
    )
    (root / "extension.py").write_text(
        """
def register(api):
    api.register_tool(
        name="demo_dynamic_fetch",
        description="Fetch remote content for approval tests",
        parameters={"type": "object", "properties": {"url": {"type": "string"}}},
        handler=lambda workspace, arguments: f"ok:{arguments.get('url', '')}",
        exact_effect_mode="required",
        requests_network_hint=True,
    )
""",
        encoding="utf-8",
    )


def test_approve_or_execute_pending_action_loads_dynamic_extensions(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("PP_AGENT_HOME", str(tmp_path / "user-home"))
    extension_dir = tmp_path / ".pp-agent" / "extensions" / "demo_dynamic"
    _write_extension(extension_dir)

    registry = create_tool_registry(tmp_path, include_dynamic_extensions=True)
    staged = registry.execute("demo_dynamic_fetch", {"url": "https://example.com/article"})
    token = staged.details["token"]

    result = approve_or_execute_pending_action(tmp_path, token, render=False)

    assert result["action_type"] == "run_extension_tool"
    assert result["result"] == "ok:https://example.com/article"
