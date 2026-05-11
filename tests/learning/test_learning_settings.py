from pp_agent.storage.settings import Settings


def test_learning_settings_defaults_are_available(tmp_path) -> None:
    settings = Settings.load(tmp_path)

    assert settings.learning.enable is True
    assert settings.learning.candidate_limit_per_turn == 3


def test_learning_settings_are_loaded_from_project_config(tmp_path) -> None:
    project_dir = tmp_path / ".pp-agent"
    project_dir.mkdir(parents=True)
    (project_dir / "config.json").write_text(
        '{"learning":{"enable":false,"auto_extract":false,"project_memory_enable":false,"project_memory_char_limit":1234,"candidate_limit_per_turn":2,"min_confidence_to_suggest":"high","llm_extractor_enable":false}}',
        encoding="utf-8",
    )

    settings = Settings.load(tmp_path)

    assert settings.learning.enable is False
    assert settings.learning.auto_extract is False
    assert settings.learning.project_memory_enable is False
    assert settings.learning.project_memory_char_limit == 1234
    assert settings.learning.candidate_limit_per_turn == 2
    assert settings.learning.min_confidence_to_suggest == "high"
    assert settings.learning.llm_extractor_enable is False
