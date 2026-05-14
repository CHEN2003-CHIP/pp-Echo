from pp_agent.storage.settings import Settings


def test_learning_settings_defaults_are_available(tmp_path) -> None:
    settings = Settings.load(tmp_path)

    assert settings.learning.enable is True
    assert settings.learning.candidate_limit_per_turn == 3
    assert settings.learning.auto_apply_memory is True
    assert settings.learning.detailed_memory_enable is True


def test_learning_settings_are_loaded_from_project_config(tmp_path) -> None:
    project_dir = tmp_path / ".pp-agent"
    project_dir.mkdir(parents=True)
    (project_dir / "config.json").write_text(
        '{"learning":{"enable":false,"auto_extract":false,"auto_apply_memory":false,"auto_apply_min_confidence":"high","project_memory_enable":false,"project_memory_char_limit":1234,"detailed_memory_enable":false,"detailed_memory_char_limit":4321,"detailed_memory_auto_consolidate":false,"detailed_memory_sync_index_after_write":false,"candidate_limit_per_turn":2,"min_confidence_to_suggest":"high","llm_extractor_enable":false}}',
        encoding="utf-8",
    )

    settings = Settings.load(tmp_path)

    assert settings.learning.enable is False
    assert settings.learning.auto_extract is False
    assert settings.learning.auto_apply_memory is False
    assert settings.learning.auto_apply_min_confidence == "high"
    assert settings.learning.project_memory_enable is False
    assert settings.learning.project_memory_char_limit == 1234
    assert settings.learning.detailed_memory_enable is False
    assert settings.learning.detailed_memory_char_limit == 4321
    assert settings.learning.detailed_memory_auto_consolidate is False
    assert settings.learning.detailed_memory_sync_index_after_write is False
    assert settings.learning.candidate_limit_per_turn == 2
    assert settings.learning.min_confidence_to_suggest == "high"
    assert settings.learning.llm_extractor_enable is False
