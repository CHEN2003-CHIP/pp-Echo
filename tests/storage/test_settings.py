from pathlib import Path

from storage.settings import Settings


def test_project_config_overrides_defaults(tmp_path: Path) -> None:
    project_dir = tmp_path / ".pp-agent"
    project_dir.mkdir(parents=True)
    (project_dir / "config.json").write_text(
        '{"model":"qwen3.5-plus","enable_thinking":false,"shell_timeout_seconds":42,"tool_confirmation":{"write_file":false}}',
        encoding="utf-8",
    )

    settings = Settings.load(tmp_path)

    assert settings.model.model == "qwen3.5-plus"
    assert settings.model.enable_thinking is False
    assert settings.tool_policy.shell_timeout_seconds == 42
    assert settings.tool_policy.confirm_write_file is False