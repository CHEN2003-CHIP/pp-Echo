from pathlib import Path

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

