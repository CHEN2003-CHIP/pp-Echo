from pathlib import Path
import re

from pp_agent.app import bootstrap
from pp_agent.app.bootstrap import (
    auto_index_scheduler_for,
    checkpoint_store_for,
    global_memory_context_hook_for,
    history_retriever_for,
    history_store_for,
    memory_provider_for,
    project_memory_context_hook_for,
    session_store_for,
    timeline_store_for,
    vector_index_for,
)


def test_bootstrap_uses_project_local_defaults_for_runtime_storage(tmp_path: Path) -> None:
    assert session_store_for(tmp_path).root == (tmp_path / ".pp-agent" / "sessions")
    assert timeline_store_for(tmp_path).root == (tmp_path / ".pp-agent" / "timelines")
    assert checkpoint_store_for(tmp_path).root == (tmp_path / ".pp-agent" / "checkpoints")


def test_bootstrap_uses_configured_runtime_storage_paths(tmp_path: Path) -> None:
    project_dir = tmp_path / ".pp-agent"
    project_dir.mkdir(parents=True)
    (project_dir / "config.json").write_text(
        '{"storage":{"sessions_dir":"state/sessions","timelines_dir":"state/timelines","checkpoints_dir":"state/checkpoints"},"memory":{"enable":true,"backend":"sqlite","sqlite_path":"state/history.db","vector_enable":true,"vector_backend":"chroma","chroma_path":"state/chroma"}}',
        encoding="utf-8",
    )

    assert session_store_for(tmp_path).root == (tmp_path / "state" / "sessions")
    assert timeline_store_for(tmp_path).root == (tmp_path / "state" / "timelines")
    assert checkpoint_store_for(tmp_path).root == (tmp_path / "state" / "checkpoints")
    assert history_store_for(tmp_path).path == (tmp_path / "state" / "history.db")
    assert vector_index_for(tmp_path).path == (tmp_path / "state" / "chroma")


def test_memory_provider_falls_back_when_sqlite_store_is_unavailable(tmp_path: Path, monkeypatch) -> None:
    project_dir = tmp_path / ".pp-agent"
    project_dir.mkdir(parents=True)
    (project_dir / "config.json").write_text('{"memory":{"enable":true,"backend":"sqlite"}}', encoding="utf-8")

    def fail_store(*_args, **_kwargs):
        raise OSError("history db unavailable")

    monkeypatch.setattr(bootstrap, "SQLiteHistoryStore", fail_store)

    provider = memory_provider_for(tmp_path)

    assert provider.__class__.__name__ == "NoopMemoryProvider"


def test_auto_index_scheduler_falls_back_when_history_store_is_unavailable(tmp_path: Path, monkeypatch) -> None:
    project_dir = tmp_path / ".pp-agent"
    project_dir.mkdir(parents=True)
    (project_dir / "config.json").write_text(
        '{"memory":{"enable":true,"backend":"sqlite","embedding_enable":true,"vector_enable":true,"vector_backend":"chroma","indexing_enable":true}}',
        encoding="utf-8",
    )

    def fail_pipeline(_workspace):
        raise OSError("history db unavailable")

    monkeypatch.setattr(bootstrap, "memory_index_pipeline_for", fail_pipeline)

    scheduler = auto_index_scheduler_for(tmp_path)

    assert scheduler.__class__.__name__ == "NoopAutoIndexScheduler"


def test_history_retriever_is_disabled_when_history_store_is_unavailable(tmp_path: Path, monkeypatch) -> None:
    project_dir = tmp_path / ".pp-agent"
    project_dir.mkdir(parents=True)
    (project_dir / "config.json").write_text(
        '{"memory":{"enable":true,"backend":"sqlite","embedding_enable":true,"vector_enable":true,"vector_backend":"chroma","retrieval_enable":true}}',
        encoding="utf-8",
    )

    def fail_store(_workspace):
        raise OSError("history db unavailable")

    monkeypatch.setattr(bootstrap, "history_store_for", fail_store)

    assert history_retriever_for(tmp_path) is None


def test_memory_context_hooks_disable_when_storage_is_unavailable(tmp_path: Path, monkeypatch) -> None:
    project_dir = tmp_path / ".pp-agent"
    project_dir.mkdir(parents=True)
    (project_dir / "config.json").write_text(
        '{"learning":{"enable":true,"project_memory_enable":true}}',
        encoding="utf-8",
    )

    class FailingProjectMemoryHook:
        def __init__(self, **_kwargs):
            raise PermissionError("project memory unavailable")

    class FailingGlobalMemoryHook:
        def __init__(self, **_kwargs):
            raise PermissionError("global memory unavailable")

    monkeypatch.setattr(bootstrap, "ProjectMemoryContextHook", FailingProjectMemoryHook)
    monkeypatch.setattr(bootstrap, "GlobalMemoryContextHook", FailingGlobalMemoryHook)

    assert project_memory_context_hook_for(tmp_path) is None
    assert global_memory_context_hook_for(tmp_path) is None


def test_chroma_collection_defaults_to_embedding_scoped_name(tmp_path: Path) -> None:
    project_dir = tmp_path / ".pp-agent"
    project_dir.mkdir(parents=True)
    (project_dir / "config.json").write_text(
        '{"memory":{"vector_enable":true,"vector_backend":"chroma","chroma_collection":"hist","embedding_provider":"dashscope","embedding_model":"text-embedding-v4"}}',
        encoding="utf-8",
    )

    index = vector_index_for(tmp_path)

    assert re.fullmatch(r"hist_[0-9a-f]{12}", index.collection_name)
    assert len(index.collection_name) <= 63


def test_chroma_collection_hash_changes_with_embedding_model(tmp_path: Path) -> None:
    project_dir = tmp_path / ".pp-agent"
    project_dir.mkdir(parents=True)
    config_path = project_dir / "config.json"
    config_path.write_text(
        '{"memory":{"vector_enable":true,"vector_backend":"chroma","chroma_collection":"hist","embedding_provider":"dashscope","embedding_model":"text-embedding-v4"}}',
        encoding="utf-8",
    )
    first_name = vector_index_for(tmp_path).collection_name
    config_path.write_text(
        '{"memory":{"vector_enable":true,"vector_backend":"chroma","chroma_collection":"hist","embedding_provider":"dashscope","embedding_model":"another-embedding-model"}}',
        encoding="utf-8",
    )

    assert vector_index_for(tmp_path).collection_name != first_name


def test_chroma_collection_scoped_name_stays_under_chroma_limit(tmp_path: Path) -> None:
    project_dir = tmp_path / ".pp-agent"
    project_dir.mkdir(parents=True)
    (project_dir / "config.json").write_text(
        '{"memory":{"vector_enable":true,"vector_backend":"chroma","chroma_collection":"very_long_project_history_collection_name_that_would_exceed_chroma_limit","embedding_provider":"dashscope","embedding_model":"very-long-embedding-model-name"}}',
        encoding="utf-8",
    )

    collection_name = vector_index_for(tmp_path).collection_name

    assert re.fullmatch(r"[a-z0-9][a-z0-9_-]{1,61}[a-z0-9]", collection_name)
    assert len(collection_name) <= 63


def test_chroma_collection_can_opt_out_of_embedding_scoped_name(tmp_path: Path) -> None:
    project_dir = tmp_path / ".pp-agent"
    project_dir.mkdir(parents=True)
    (project_dir / "config.json").write_text(
        '{"memory":{"vector_enable":true,"vector_backend":"chroma","chroma_collection":"hist","embedding_model":"text-embedding-v4","chroma_collection_per_embedding":false}}',
        encoding="utf-8",
    )

    index = vector_index_for(tmp_path)

    assert index.collection_name == "hist"

