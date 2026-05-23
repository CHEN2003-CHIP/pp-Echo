from __future__ import annotations

import json

import pytest

from pp_agent.config import ConfigConflictError, ConfigManager, ConfigValidationError
from pp_agent.config.patch import merge_patch
from pp_agent.config.runtime_overrides import runtime_overrides


def test_json_merge_patch_semantics() -> None:
    target = {"a": {"b": 1, "c": 2}, "items": [1, 2], "keep": True}
    patch = {"a": {"b": None, "d": 3}, "items": [3], "keep": None}

    assert merge_patch(target, patch) == {"a": {"c": 2, "d": 3}, "items": [3]}


def test_project_config_hash_conflict_rejects_stale_write(tmp_path) -> None:
    manager = ConfigManager(tmp_path)
    original = manager.get_effective_snapshot().config_hash
    manager.set_path("model.model", "first-model", base_hash=original)

    with pytest.raises(ConfigConflictError):
        manager.set_path("model.model", "second-model", base_hash=original)


def test_schema_validation_rejects_unknown_project_path(tmp_path) -> None:
    manager = ConfigManager(tmp_path)

    with pytest.raises(ValueError, match="Unknown config path"):
        manager.patch_project_config({"unknown_section": {"value": True}})


def test_project_config_is_persisted_atomically_after_validation(tmp_path) -> None:
    manager = ConfigManager(tmp_path)
    snapshot = manager.set_path("tool_policy.shell_timeout_seconds", 44)

    saved = json.loads((tmp_path / ".pp-agent" / "config.json").read_text(encoding="utf-8"))
    assert saved["tool_policy"]["shell_timeout_seconds"] == 44
    assert snapshot.settings.tool_policy.shell_timeout_seconds == 44


def test_session_model_override_precedes_project_config(tmp_path) -> None:
    manager = ConfigManager(tmp_path)
    manager.set_path("model.model", "project-model")
    snapshot = manager.set_session_model("session-1", "provider/session-model")

    assert snapshot.settings.model.model == "provider/session-model"
    assert snapshot.session_config["model"]["model"] == "provider/session-model"
    assert manager.get_effective_snapshot().settings.model.model == "project-model"


def test_profile_precedes_project_and_session_precedes_profile(tmp_path) -> None:
    manager = ConfigManager(tmp_path)
    manager.patch_project_config(
        {
            "model": {"model": "project-model"},
            "active_profile": "fast",
            "profiles": {"fast": {"model": {"model": "profile-model"}}},
        }
    )

    profile_snapshot = manager.get_effective_snapshot(session_id="session-1")
    assert profile_snapshot.active_profile == "fast"
    assert profile_snapshot.profile_config["model"]["model"] == "profile-model"
    assert profile_snapshot.settings.model.model == "profile-model"
    assert profile_snapshot.source_map["model.model"] == "profile:fast"

    session_snapshot = manager.set_session_path("session-1", "model.model", "session-model")
    assert session_snapshot.settings.model.model == "session-model"
    assert session_snapshot.source_map["model.model"] == "session"


def test_session_can_select_profile(tmp_path) -> None:
    manager = ConfigManager(tmp_path)
    manager.patch_project_config(
        {
            "active_profile": "safe",
            "profiles": {
                "safe": {"model": {"temperature": 0}},
                "creative": {"model": {"temperature": 0.8}},
            },
        }
    )

    snapshot = manager.set_session_profile("session-1", "creative")

    assert snapshot.active_profile == "creative"
    assert snapshot.settings.model.temperature == 0.8
    assert snapshot.session_config["active_profile"] == "creative"


def test_profile_validation_reports_structured_errors(tmp_path) -> None:
    manager = ConfigManager(tmp_path)

    with pytest.raises(ConfigValidationError) as exc_info:
        manager.patch_project_config({"profiles": {"bad": {"unknown": True}}})

    assert exc_info.value.errors[0]["path"] == "profiles.bad.unknown"


def test_pending_effects_reflect_reload_policy(tmp_path) -> None:
    manager = ConfigManager(tmp_path)
    snapshot = manager.set_path("tool_policy.shell_timeout_seconds", 44)

    assert "tool_policy.shell_timeout_seconds:rebuild_runtime" in snapshot.pending_effects
    assert snapshot.reload_policy == "rebuild_runtime"


def test_runtime_debug_override_is_not_persisted(tmp_path) -> None:
    manager = ConfigManager(tmp_path)
    snapshot = manager.set_runtime_override("debug.trace", True)

    assert snapshot.runtime_config["debug"]["trace"] is True
    assert not (tmp_path / ".pp-agent" / "config.json").exists()
    runtime_overrides.clear(tmp_path)
    assert manager.get_effective_snapshot().runtime_config == {}
