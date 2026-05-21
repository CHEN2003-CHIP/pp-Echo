from __future__ import annotations

from typing import Any, Literal, Optional

from pydantic import BaseModel, Field


BrowserAction = Literal[
    "doctor",
    "status",
    "start",
    "stop",
    "profiles",
    "tabs.open",
    "tabs.list",
    "tabs.focus",
    "tabs.close",
    "snapshot",
    "screenshot",
    "navigate",
    "act",
]
BrowserTarget = Literal["host", "sandbox", "node"]
BrowserProfileName = Literal["default", "isolated", "user", "remote"]
BrowserActKind = Literal[
    "click",
    "type",
    "press",
    "hover",
    "drag",
    "select",
    "fill",
    "wait",
    "evaluate",
    "resize",
    "close",
]


class BrowserBounds(BaseModel):
    x: float = 0
    y: float = 0
    width: float = 0
    height: float = 0


class BrowserNode(BaseModel):
    ref: str
    role: str = ""
    text: str = ""
    name: str = ""
    label: str = ""
    placeholder: str = ""
    href: str = ""
    visible: bool = True
    bounds: BrowserBounds = Field(default_factory=BrowserBounds)
    selector: str = Field(default="", exclude=True)

    def model_facing(self) -> dict[str, Any]:
        payload = self.model_dump(exclude={"selector"}, mode="python")
        return payload


class BrowserSnapshot(BaseModel):
    snapshot_id: str
    target_id: str = ""
    url: str
    title: str
    ready_state: str
    body_text: str = ""
    html: Optional[str] = None
    nodes: list[BrowserNode] = Field(default_factory=list)
    stats: dict[str, Any] = Field(default_factory=dict)
    untrusted_web_content: bool = True

    def compact_text(self, max_chars: int = 240) -> str:
        body_text = self.body_text.strip().replace("\n", " ")
        summary = body_text[:max_chars]
        if len(body_text) > max_chars:
            summary += "..."
        return summary


class BrowserProfile(BaseModel):
    name: BrowserProfileName
    mode: str
    user_data_dir: str = ""
    cdp_url: str = ""
    attach_only: bool = False
    enabled: bool = True
    explicitly_enabled: bool = False


class BrowserTab(BaseModel):
    tab_id: str
    target_id: str
    label: str = ""
    url: str = ""
    title: str = ""
    active: bool = False


class BrowserSnapshotOptions(BaseModel):
    refs: bool = True
    interactive: bool = True
    compact: bool = True
    max_chars: int = 4000
    selector: Optional[str] = None
    frame: Optional[str] = None


class BrowserScreenshotOptions(BaseModel):
    filename: Optional[str] = None
    full_page: bool = True


class BrowserActRequest(BaseModel):
    kind: BrowserActKind
    ref: Optional[str] = None
    text: Optional[str] = None
    key: Optional[str] = None
    values: list[str] = Field(default_factory=list)
    fields: dict[str, str] = Field(default_factory=dict)
    timeout_ms: Optional[int] = None
    width: Optional[int] = None
    height: Optional[int] = None
    selector: Optional[str] = None
    expression: Optional[str] = None


class BrowserToolArgs(BaseModel):
    action: BrowserAction
    target: BrowserTarget = "host"
    profile: BrowserProfileName = "default"
    target_id: Optional[str] = None
    url: Optional[str] = None
    label: Optional[str] = None
    request: Optional[BrowserActRequest] = None
    snapshot_options: BrowserSnapshotOptions = Field(default_factory=BrowserSnapshotOptions)
    screenshot_options: BrowserScreenshotOptions = Field(default_factory=BrowserScreenshotOptions)
    wait_ms: Optional[int] = None


class BrowserActResult(BaseModel):
    snapshot: BrowserSnapshot
    action: str
    requires_resnapshot: bool = False
    stale_ref: bool = False
    details: dict[str, Any] = Field(default_factory=dict)
