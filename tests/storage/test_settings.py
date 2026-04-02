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


def test_capability_settings_are_loaded_from_project_config(tmp_path: Path) -> None:
    project_dir = tmp_path / ".pp-agent"
    project_dir.mkdir(parents=True)
    (project_dir / "config.json").write_text(
        '{"capabilities":{"builtin_tools":{"enable":false},"skills":{"enable_builtin":false,"custom_directories":["C:/skills"],"include":["review*"],"ignored":["review-draft"]},"mcp":{"enable":true,"config_paths":["C:/mcp.json"],"server_filters":["github*"]},"extensions":{"enable_builtin":true,"custom_directories":["C:/ext"],"include":["adapter*"],"ignored":["draft*"]}}}',
        encoding="utf-8",
    )

    settings = Settings.load(tmp_path)

    assert settings.capabilities.builtin_tools.enable is False
    assert settings.capabilities.skills.enable_builtin is False
    assert settings.capabilities.skills.custom_directories == ["C:/skills"]
    assert settings.capabilities.skills.include == ["review*"]
    assert settings.capabilities.skills.ignored == ["review-draft"]
    assert settings.capabilities.mcp.enable is True
    assert settings.capabilities.mcp.config_paths == ["C:/mcp.json"]
    assert settings.capabilities.mcp.server_filters == ["github*"]
    assert settings.capabilities.extensions.enable_builtin is True
    assert settings.capabilities.extensions.custom_directories == ["C:/ext"]
    assert settings.capabilities.extensions.include == ["adapter*"]
    assert settings.capabilities.extensions.ignored == ["draft*"]
