from __future__ import annotations

from pathlib import Path

from pp_agent.api import sdk


class FakeHost:
    def create_checkpoint(self, workspace: Path, **kwargs):
        return type("Result", (), {"model_dump": lambda self, mode="json": {"checkpoint_id": "cp-1", "snapshot_type": kwargs["snapshot_type"]}})()

    def list_checkpoints(self, workspace: Path, *, session_id=None):
        return [type("Result", (), {"model_dump": lambda self, mode="json": {"checkpoint_id": "cp-1", "session_id": session_id}})()]

    def preview_rewind(self, workspace: Path, session_id: str, **kwargs):
        return type("Result", (), {"model_dump": lambda self, mode="json": {"session_id": session_id, "mode": kwargs["mode"]}})()

    def rewind_safe(self, workspace: Path, session_id: str, **kwargs):
        return type("Result", (), {"model_dump": lambda self, mode="json": {"session_id": "rewound", "mode": kwargs["mode"], "restored_workspace": True}})()


def test_sdk_checkpoint_endpoints_delegate_to_host(tmp_path: Path) -> None:
    checkpoint = sdk.create_checkpoint(tmp_path, "session-1", host=FakeHost(), snapshot_type="head_snapshot")
    listing = sdk.list_checkpoints(tmp_path, session_id="session-1", host=FakeHost())
    preview = sdk.preview_rewind(tmp_path, "session-1", host=FakeHost(), mode="workspace_only")
    rewind = sdk.rewind_safe(tmp_path, "session-1", host=FakeHost(), mode="conversation_and_workspace")

    assert checkpoint["checkpoint_id"] == "cp-1"
    assert listing == [{"checkpoint_id": "cp-1", "session_id": "session-1"}]
    assert preview["mode"] == "workspace_only"
    assert rewind["restored_workspace"] is True
