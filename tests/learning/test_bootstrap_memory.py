from pathlib import Path

from pp_agent.domain import ChatMessage, TextPart
from pp_agent.learning.bootstrap_memory import BootstrapMemoryManager, GlobalBootstrapMemoryManager, MANAGED_BEGIN, MANAGED_END
from pp_agent.learning.context import GlobalMemoryContextHook, ProjectMemoryContextHook
from pp_agent.learning.models import LearningSettings
from pp_agent.learning.store import LearningStore


def test_bootstrap_memory_sync_preserves_user_content_and_adds_navigation(tmp_path: Path) -> None:
    (tmp_path / "MEMORY.md").write_text("# Manual Notes\n\nKeep this human note.\n", encoding="utf-8")
    memory_dir = tmp_path / "memory"
    memory_dir.mkdir()
    (memory_dir / "agent-safety.md").write_text("# Agent Safety\n\nDetailed notes.", encoding="utf-8")
    manager = BootstrapMemoryManager(workspace=tmp_path, settings=LearningSettings())

    result = manager.sync("- **Run tests**: User prefers pytest.")
    content = result.path.read_text(encoding="utf-8")

    assert "# Manual Notes" in content
    assert "Keep this human note." in content
    assert MANAGED_BEGIN in content
    assert MANAGED_END in content
    assert "User prefers pytest" in content
    assert "`memory/agent-safety.md` - Agent Safety" in content
    assert (memory_dir / "agent-safety.md").read_text(encoding="utf-8") == "# Agent Safety\n\nDetailed notes."


def test_bootstrap_memory_sync_replaces_only_managed_section(tmp_path: Path) -> None:
    manager = BootstrapMemoryManager(workspace=tmp_path, settings=LearningSettings())

    manager.sync("- **Old**: old memory")
    manager.sync("- **New**: new memory")
    content = (tmp_path / "MEMORY.md").read_text(encoding="utf-8")

    assert "new memory" in content
    assert "old memory" not in content
    assert content.count(MANAGED_BEGIN) == 1


def test_bootstrap_memory_sync_compacts_managed_section(tmp_path: Path) -> None:
    settings = LearningSettings(project_memory_char_limit=700)
    manager = BootstrapMemoryManager(workspace=tmp_path, settings=settings)
    long_memory = "\n".join(f"- **Item {index}**: " + ("detail " * 20) for index in range(50))

    result = manager.sync(long_memory)

    assert result.managed_chars <= settings.project_memory_char_limit
    assert "pp-Echo Workspace Bootstrap Memory" in manager.read()


def test_project_memory_context_hook_prefers_root_memory(tmp_path: Path) -> None:
    settings = LearningSettings()
    store = LearningStore(tmp_path / ".pp-agent" / "learning")
    store.append_project_memory("- legacy memory")
    (tmp_path / "MEMORY.md").write_text("# Project Memory\n\nroot bootstrap memory", encoding="utf-8")
    hook = ProjectMemoryContextHook(workspace=tmp_path, settings=settings, store=store)
    messages = [ChatMessage(role="system", content=[TextPart(text="system")], timestamp=0)]

    transformed = hook.transform_context(None, messages)  # type: ignore[arg-type]
    injected = transformed[1].content[0].text

    assert "root bootstrap memory" in injected
    assert "legacy memory" not in injected


def test_project_memory_context_hook_falls_back_to_legacy_memory(tmp_path: Path) -> None:
    settings = LearningSettings()
    store = LearningStore(tmp_path / ".pp-agent" / "learning")
    store.append_project_memory("- legacy memory")
    hook = ProjectMemoryContextHook(workspace=tmp_path, settings=settings, store=store)
    messages = [ChatMessage(role="system", content=[TextPart(text="system")], timestamp=0)]

    transformed = hook.transform_context(None, messages)  # type: ignore[arg-type]

    assert "legacy memory" in transformed[1].content[0].text


def test_global_bootstrap_memory_manager_uses_global_title(tmp_path: Path) -> None:
    manager = GlobalBootstrapMemoryManager(global_root=tmp_path, settings=LearningSettings())

    manager.sync("- User prefers focused tests first.")

    content = (tmp_path / "MEMORY.md").read_text(encoding="utf-8")
    assert "# Global Memory" in content
    assert "pp-Echo Global User Bootstrap Memory" in content


def test_global_memory_context_hook_injects_global_memory(tmp_path: Path) -> None:
    settings = LearningSettings()
    global_root = tmp_path / "global"
    global_root.mkdir()
    (global_root / "MEMORY.md").write_text("# Global Memory\n\nAlways answer in Chinese.\n", encoding="utf-8")
    hook = GlobalMemoryContextHook(workspace=tmp_path, settings=settings, global_root=global_root)
    messages = [ChatMessage(role="system", content=[TextPart(text="system")], timestamp=0)]

    transformed = hook.transform_context(None, messages)  # type: ignore[arg-type]

    assert "Always answer in Chinese." in transformed[1].content[0].text
