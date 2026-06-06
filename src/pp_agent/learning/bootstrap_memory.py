from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from pp_agent.learning.models import LearningSettings


MANAGED_BEGIN = "<!-- pp-echo-memory:begin -->"
MANAGED_END = "<!-- pp-echo-memory:end -->"


@dataclass(frozen=True)
class BootstrapMemorySyncResult:
    path: Path
    chars: int
    managed_chars: int


class BootstrapMemoryManager:
    """
    项目级 bootstrap memory 管理器。

    BootstrapMemoryManager 负责读取、初始化和维护 workspace 的长期项目记忆。
    这些记忆通常包括项目结构、架构决策、调试经验、常用命令、约定规则等，
    会在 Runtime 构造上下文时通过 ProjectMemoryContextHook 注入给模型。

    它不负责对话历史写入、向量索引、BM25 检索或 LLM 抽取；
    它更像是项目启动时的长期上下文提供者。

    简单说：
    它管理“Agent 进入这个项目时应该先知道什么”。
    """
   
    #Learned Notes：从项目学习系统提取的简洁记忆（例如用户偏好、项目约定）。
    #Detailed Memory Index：自动扫描 workspace/memory/ 目录下的所有 *.md 文件，生成一个带标题的链接列表，方便 AI 或用户快速定位详细笔记。
    def __init__(
        self,
        *,
        workspace: Path,
        settings: LearningSettings,
        path: Path | None = None,
        label: str = "Workspace",
        document_title: str = "Project Memory",
    ) -> None:
        self.workspace = workspace.resolve()
        self.settings = settings
        self.path = (path or (self.workspace / "MEMORY.md")).resolve()
        self.label = label
        self.document_title = document_title

    def read(self) -> str:
        if not self.path.exists():
            return ""
        try:
            return self.path.read_text(encoding="utf-8-sig")
        except OSError:
            return ""

    def sync(self, project_memory: str) -> BootstrapMemorySyncResult:
        """将传入的 project_memory（一个包含项目级记忆的文本，通常来自 LearningStore.read_project_memory()）
        同步到 MEMORY.md 文件的受管理区域。"""
        managed = self._managed_section(project_memory)
        existing = self.read()
        content = self._replace_managed_section(existing, managed)
        self.path.write_text(content, encoding="utf-8")
        return BootstrapMemorySyncResult(path=self.path, chars=len(content), managed_chars=len(managed))

    def _managed_section(self, project_memory: str) -> str:
        """生成受管理区域的完整 Markdown 文本。"""
        notes = _compact_bullets(project_memory, limit=max(400, self.settings.project_memory_char_limit - 900))
        navigation = self._memory_navigation(limit=1200)
        parts = [
            MANAGED_BEGIN,
            f"## pp-Echo {self.label} Bootstrap Memory",
            "",
            "Short-lived prompt memory for durable preferences, project decisions, and navigation.",
            "Use `memory_search` and `memory_get` for detailed notes in `memory/**/*.md`.",
            "",
            "### Learned Notes",
            notes or "- No applied project memory yet.",
            "",
            "### Detailed Memory Index",
            navigation or "- No detailed memory markdown files found.",
            MANAGED_END,
        ]
        managed = "\n".join(parts).strip() + "\n"
        if len(managed) <= self.settings.project_memory_char_limit:
            return managed
        notes_budget = max(
            200,
            self.settings.project_memory_char_limit - len(management_shell(navigation, label=self.label)),
        )
        compact_notes = _compact_bullets(project_memory, limit=notes_budget)
        return "\n".join(
            [
                MANAGED_BEGIN,
                f"## pp-Echo {self.label} Bootstrap Memory",
                "",
                "Short-lived prompt memory for durable preferences, project decisions, and navigation.",
                "Use `memory_search` and `memory_get` for detailed notes in `memory/**/*.md`.",
                "",
                "### Learned Notes",
                compact_notes or "- No applied project memory yet.",
                "",
                "### Detailed Memory Index",
                navigation or "- No detailed memory markdown files found.",
                MANAGED_END,
            ]
        ).strip() + "\n"

    def _memory_navigation(self, *, limit: int) -> str:
        """扫描 workspace/memory/ 目录，生成一个 Markdown 无序列表，每一项格式为 - \相对路径` - 标题`。"""
        memory_dir = self.workspace / "memory"
        if not memory_dir.exists():
            return ""
        lines: list[str] = []
        for path in sorted(memory_dir.rglob("*.md")):
            if not path.is_file():
                continue
            try:
                resolved = path.resolve()
                resolved.relative_to(self.workspace)
            except (OSError, ValueError):
                continue
            rel = path.relative_to(self.workspace).as_posix()
            heading = _first_heading(path) or path.stem.replace("-", " ").replace("_", " ").title()
            lines.append(f"- `{rel}` - {heading}")
            if len("\n".join(lines)) >= limit:
                lines.append("- More detailed memory files exist; use `memory_search` for discovery.")
                break
        return "\n".join(lines)[:limit].rstrip()

    def learned_notes(self) -> str:
        """从当前 MEMORY.md 文件中提取出 ### Learned Notes 与 ### Detailed Memory Index（或 MANAGED_END）之间的内容，
        即上一次同步时写入的“Learned Notes”部分。可用于读取当前已存储的项目记忆。"""
        content = self.read()
        start = content.find("### Learned Notes")
        if start == -1:
            return ""
        start += len("### Learned Notes")
        end = content.find("### Detailed Memory Index", start)
        if end == -1:
            end = content.find(MANAGED_END, start)
        if end == -1:
            return ""
        return content[start:end].strip()

    def _replace_managed_section(self, existing: str, managed: str) -> str:
        if not existing.strip():
            return f"# {self.document_title}\n\n" + managed if managed.startswith(MANAGED_BEGIN) else managed
        start = existing.find(MANAGED_BEGIN)
        end = existing.find(MANAGED_END)
        if start != -1 and end != -1 and end >= start:
            end += len(MANAGED_END)
            return (existing[:start].rstrip() + "\n\n" + managed + existing[end:].lstrip()).strip() + "\n"
        return existing.rstrip() + "\n\n" + managed


class GlobalBootstrapMemoryManager(BootstrapMemoryManager):
    def __init__(self, *, global_root: Path, settings: LearningSettings) -> None:
        super().__init__(
            workspace=global_root,
            settings=settings,
            path=global_root / "MEMORY.md",
            label="Global User",
            document_title="Global Memory",
        )


def management_shell(navigation: str, *, label: str = "Project") -> str:
    """返回一个“空壳”受管理区域的 Markdown 字符串"""
    return "\n".join(
        [
            MANAGED_BEGIN,
            f"## pp-Echo {label} Bootstrap Memory",
            "Short-lived prompt memory for durable preferences, project decisions, and navigation.",
            "Use `memory_search` and `memory_get` for detailed notes in `memory/**/*.md`.",
            "### Learned Notes",
            "### Detailed Memory Index",
            navigation,
            MANAGED_END,
        ]
    )


def _compact_bullets(text: str, *, limit: int) -> str:
    seen: set[str] = set()
    lines: list[str] = []
    for raw_line in text.splitlines():
        line = raw_line.rstrip()
        if not line.strip():
            continue
        key = " ".join(line.lower().split())
        if key in seen:
            continue
        seen.add(key)
        lines.append(line)
    compact = "\n".join(lines).strip()
    if len(compact) <= limit:
        return compact
    kept: list[str] = []
    total = 0
    for line in reversed(lines):
        needed = len(line) + (1 if kept else 0)
        if total + needed > limit:
            continue
        kept.append(line)
        total += needed
    kept.reverse()
    return "\n".join(kept).strip()


def _first_heading(path: Path) -> str:
    try:
        for raw_line in path.read_text(encoding="utf-8-sig").splitlines():
            line = raw_line.strip()
            if line.startswith("#"):
                return line.lstrip("#").strip()
    except OSError:
        return ""
    return ""


__all__ = [
    "BootstrapMemoryManager",
    "BootstrapMemorySyncResult",
    "GlobalBootstrapMemoryManager",
    "MANAGED_BEGIN",
    "MANAGED_END",
]
