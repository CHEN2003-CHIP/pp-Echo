from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal, Optional


UIStatus = Literal[
    "idle",
    "typing",
    "slash_popup_open",
    "thinking",
    "running_command",
    "streaming_output",
    "waiting_for_approval",
    "diff_ready",
    "task_complete",
    "error",
]
FocusTarget = Literal["composer", "transcript", "slash_popup", "attachments", "approval_actions"]
TranscriptFollowMode = Literal["pinned_to_bottom", "detached_from_bottom"]
BlockType = Literal[
    "user",
    "assistant_status",
    "thinking",
    "running_command",
    "stdout",
    "stderr",
    "tool_result",
    "diff_summary",
    "approval_request",
    "final_answer",
    "error",
    "warning",
    "task_complete",
]
BlockTone = Literal["default", "muted", "accent", "warning", "error", "success"]
BlockFamily = Literal["conversation", "status", "command", "output", "diff", "approval", "completion"]
BlockDensity = Literal["compact", "normal", "dense"]
BlockEmphasis = Literal["low", "normal", "high", "critical"]


@dataclass
class AttachmentChip:
    id: str
    name: str
    type_label: str
    removable: bool = True


@dataclass
class SlashCommandItem:
    name: str
    description: str


@dataclass
class SlashPopupState:
    open: bool = False
    query: str = ""
    selected_index: int = 0
    items: list[SlashCommandItem] = field(default_factory=list)


@dataclass
class TuiBlock:
    id: str
    block_type: BlockType
    title: str
    body: str = ""
    meta: list[str] = field(default_factory=list)
    tone: BlockTone = "default"
    collapsed: bool = False
    collapsed_preview_lines: int = 8
    streaming: bool = False
    status_label: str = ""
    command_text: str = ""
    command_exit_code: Optional[int] = None
    duration_ms: Optional[int] = None
    actions_hint: str = ""
    navigable: bool = True
    important: bool = False
    anchor_line_count: int = 0
    family: BlockFamily = "status"
    density: BlockDensity = "normal"
    emphasis: BlockEmphasis = "normal"
    expandable_hint: str = ""


SLASH_COMMANDS: list[SlashCommandItem] = [
    SlashCommandItem(name="/help", description="Show available commands and shortcuts."),
    SlashCommandItem(name="/model", description="Show the current model in the header context."),
    SlashCommandItem(name="/theme", description="Show the active TUI theme tokens."),
    SlashCommandItem(name="/clear", description="Clear the current transcript view in TUI only."),
    SlashCommandItem(name="/diff", description="Jump to or summarize the latest diff-like block."),
    SlashCommandItem(name="/approvals", description="Show the current approval state and next action."),
    SlashCommandItem(name="/attachments", description="Show the current attachment chips."),
]


def filter_slash_commands(query: str) -> list[SlashCommandItem]:
    needle = query.strip().lower()
    if not needle:
        return list(SLASH_COMMANDS)
    return [item for item in SLASH_COMMANDS if needle in item.name.lower() or needle in item.description.lower()]


def is_output_like(block: TuiBlock) -> bool:
    return block.block_type in {"stdout", "stderr", "diff_summary", "tool_result", "running_command"}


def is_important_block(block: TuiBlock) -> bool:
    return block.important or block.block_type in {"approval_request", "diff_summary", "error", "final_answer", "warning"}


def default_block_family(block_type: BlockType) -> BlockFamily:
    mapping: dict[BlockType, BlockFamily] = {
        "user": "conversation",
        "assistant_status": "status",
        "thinking": "status",
        "running_command": "command",
        "stdout": "output",
        "stderr": "output",
        "tool_result": "output",
        "diff_summary": "diff",
        "approval_request": "approval",
        "final_answer": "conversation",
        "error": "completion",
        "warning": "completion",
        "task_complete": "completion",
    }
    return mapping.get(block_type, "status")
