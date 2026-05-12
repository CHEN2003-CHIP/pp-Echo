from pathlib import Path
import re

from pp_agent.app.bootstrap import checkpoint_store_for, history_store_for, session_store_for, timeline_store_for, vector_index_for


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

