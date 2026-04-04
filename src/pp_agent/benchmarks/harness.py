from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
import time
from collections.abc import Iterator
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from pp_agent.app.extensions_runtime import load_executable_extensions
from pp_agent.benchmarks.models import BenchmarkSuiteResult, BenchmarkTask, BenchmarkTaskResult, ModeResult
from pp_agent.benchmarks.token_proxy import estimate_messages
from pp_agent.domain import ChatMessage, TextPart
from pp_agent.llm.models import ModelConfig
from pp_agent.runtime.runtime import AgentRuntime
from pp_agent.runtime.session_host import SessionHost
from pp_agent.runtime.state import AgentEvent
from pp_agent.storage.approvals import PendingActionStore
from pp_agent.storage.checkpoints import CheckpointStore
from pp_agent.storage.sessions import SessionStore
from pp_agent.storage.settings import Settings
from pp_agent.tools.registry import ToolRegistry


class ToolPlanLLMClient:
    def __init__(self, tool_name: str, arguments: dict[str, Any], final_text: str = "done") -> None:
        self.tool_name = tool_name
        self.arguments = arguments
        self.final_text = final_text
        self.calls = 0
        self.model = ModelConfig()

    def stream_chat(self, _messages, tools=None) -> Iterator[dict[str, Any]]:
        self.calls += 1
        if self.calls == 1:
            yield {
                "text": "",
                "tool_calls": [{"id": "call-1", "name": self.tool_name, "arguments_chunk": json.dumps(self.arguments, ensure_ascii=False)}],
                "finish_reason": "tool_calls",
                "raw": {},
            }
            return
        yield {"text": self.final_text, "tool_calls": [], "finish_reason": "stop", "raw": {}}


class EchoLLMClient:
    def __init__(self) -> None:
        self.model = ModelConfig()

    def stream_chat(self, messages, tools=None) -> Iterator[dict[str, Any]]:
        latest_user = ""
        for message in reversed(messages):
            if message.role != "user":
                continue
            latest_user = " ".join(part.text for part in message.content if isinstance(part, TextPart))
            break
        yield {"text": f"ack:{latest_user}", "tool_calls": [], "finish_reason": "stop", "raw": {}}


class FetchTrackingClient:
    def __init__(self, events: list[str]) -> None:
        self.events = events

    def initialize(self) -> None:
        self.events.append("initialize")

    def list_tools(self) -> list[dict[str, Any]]:
        self.events.append("list_tools")
        return [
            {"name": "fetch_markdown", "description": "Fetch webpage markdown", "input_schema": {"type": "object", "properties": {"url": {"type": "string"}}}},
            {"name": "fetch_readable", "description": "Fetch readable article", "input_schema": {"type": "object", "properties": {"url": {"type": "string"}}}},
        ]

    def list_resources(self) -> list[dict[str, Any]]:
        self.events.append("list_resources")
        return []

    def list_prompts(self) -> list[dict[str, Any]]:
        self.events.append("list_prompts")
        return []

    def call_tool(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        self.events.append(f"call_tool:{name}")
        return {"content": f"{name}:{arguments.get('url', '')}", "payload": {}, "is_error": False}

    def read_resource(self, uri: str) -> dict[str, Any]:
        raise AssertionError(uri)

    def get_prompt(self, name: str, arguments: dict[str, Any] | None = None) -> dict[str, Any]:
        raise AssertionError(name)

    def close(self) -> None:
        self.events.append("close")


class NoopLLMClient:
    def __init__(self) -> None:
        self.model = ModelConfig()

    def stream_chat(self, _messages, tools=None) -> Iterator[dict[str, Any]]:
        yield {"text": "ok", "tool_calls": [], "finish_reason": "stop", "raw": {}}


def load_tasks(repo_root: Path, suite: str) -> list[BenchmarkTask]:
    path = repo_root / "benchmarks" / "tasks" / f"{suite}.json"
    payload = json.loads(path.read_text(encoding="utf-8-sig"))
    return [BenchmarkTask(**item) for item in payload]


def run_suite(
    repo_root: Path,
    *,
    suite: str = "core",
    artifacts_dir: Optional[Path] = None,
    docs_output: Optional[Path] = None,
) -> tuple[BenchmarkSuiteResult, Optional[Path]]:
    tasks = load_tasks(repo_root, suite)
    results: list[BenchmarkTaskResult] = []
    for task in tasks:
        modes = [
            _run_task_mode(repo_root, task, mode="pp-echo"),
            _run_task_mode(repo_root, task, mode=task.baseline_mode),
        ]
        results.append(BenchmarkTaskResult(task_id=task.id, group=task.group, title=task.title, modes=modes))

    generated_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    suite_result = BenchmarkSuiteResult(
        suite=suite,
        generated_at=generated_at,
        task_count=len(tasks),
        fixture_root=str((repo_root / "benchmarks" / "fixtures").resolve()),
        results=results,
    )
    suite_result.aggregate_metrics = _aggregate_metrics(suite_result)
    suite_result.headline_results = _headline_results(suite_result)
    suite_result.notes = [
        "All results come from deterministic offline benchmark tasks in this repository.",
        "Token values are normalized proxy estimates based on message and tool payload size, not provider billing data.",
    ]

    artifact_path: Optional[Path] = None
    if artifacts_dir is not None:
        artifacts_dir.mkdir(parents=True, exist_ok=True)
        artifact_path = artifacts_dir / f"{suite}-{generated_at.replace(':', '').replace('-', '')}.json"
        artifact_path.write_text(json.dumps(suite_result.model_dump(mode="json"), ensure_ascii=False, indent=2), encoding="utf-8")
    if docs_output is not None:
        docs_output.parent.mkdir(parents=True, exist_ok=True)
        docs_output.write_text(render_markdown(suite_result), encoding="utf-8")
    return suite_result, artifact_path


def render_markdown(result: BenchmarkSuiteResult) -> str:
    metrics = result.aggregate_metrics
    lines = [
        "# pp-Echo Benchmark Report",
        "",
        f"Generated: `{result.generated_at}`",
        "",
        "## What was measured",
        "",
        "This benchmark suite measures deterministic runtime behaviors that pp-Echo is designed to improve: planner approvals, safe rewind, session branching, MCP lazy activation, and long-context compaction.",
        "",
        "## Test matrix",
        "",
        f"- Suite: `{result.suite}`",
        f"- Tasks: `{result.task_count}`",
        "- Modes: `pp-echo` vs internal baseline",
        "- Model usage: deterministic fake LLM clients only",
        "- Token numbers: normalized proxy estimates, not provider billing usage",
        "",
        "## Headline results",
        "",
    ]
    lines.extend(f"- {item}" for item in result.headline_results)
    lines.extend(
        [
            "",
            "## Metric table",
            "",
            "| Metric | Value |",
            "| --- | --- |",
        ]
    )
    for key in sorted(metrics):
        value = metrics[key]
        rendered = f"{value:.3f}" if isinstance(value, float) else str(value)
        lines.append(f"| `{key}` | `{rendered}` |")
    lines.extend(
        [
            "",
            "## Methodology",
            "",
            "- Planner gating tasks compare `require_plan_approval=True` against a baseline with the gate disabled.",
            "- Safe rewind tasks compare real rewind flows against a no-recovery baseline.",
            "- MCP tasks compare lazy discovery against eager pre-discovery in the same fixture.",
            "- Compaction tasks compare normal compaction against a baseline with compaction effectively disabled.",
            "- Session branching tasks validate branch, rewind, and tree semantics with a deterministic local runtime.",
            "",
            "## Limitations",
            "",
        ]
    )
    lines.extend(f"- {item}" for item in result.notes)
    return "\n".join(lines).strip() + "\n"


def _run_task_mode(repo_root: Path, task: BenchmarkTask, *, mode: str) -> ModeResult:
    with tempfile.TemporaryDirectory(prefix=f"pp-echo-bench-{task.group}-") as tmp:
        workspace = Path(tmp)
        _prepare_workspace(repo_root, task.fixture, workspace)
        runner = _SCENARIOS[task.scenario]
        return runner(workspace, task, mode)


def _prepare_workspace(repo_root: Path, fixture: str, workspace: Path) -> None:
    source = repo_root / "benchmarks" / "fixtures" / fixture
    if not source.exists():
        raise FileNotFoundError(f"Benchmark fixture not found: {fixture}")
    shutil.copytree(source, workspace, dirs_exist_ok=True)


def _create_runtime(
    workspace: Path,
    *,
    llm_client,
    require_plan_approval: bool = False,
    compact_after_messages: int = 8,
    max_context_messages: int = 12,
    enable_mcp: bool = False,
    transport_factory=None,
) -> AgentRuntime:
    settings = Settings.load(workspace)
    settings.capabilities.mcp.enable = enable_mcp
    tool_registry = ToolRegistry(workspace, policy=settings.tool_policy)
    session_store = SessionStore(workspace / "sessions")
    record = session_store.create(settings.system_prompt, settings.model.model_copy(deep=True))
    session_store.save(record)
    runtime = AgentRuntime(
        llm_client=llm_client,
        tool_registry=tool_registry,
        session_store=session_store,
        session_id=record.id,
        system_prompt=settings.system_prompt,
        confirm_callback=lambda _name, _args: True,
        max_context_messages=max_context_messages,
        compact_after_messages=compact_after_messages,
        require_plan_approval=require_plan_approval,
    )
    runtime.restore_session_record(record, emit_event=False)
    if enable_mcp:
        extension_runtime = load_executable_extensions(
            workspace,
            settings=settings,
            tool_registry=tool_registry,
            runtime_hooks=runtime.runtime_hooks,
            transport_factory=transport_factory,
        )
        setattr(runtime, "mcp_runtime", extension_runtime.mcp_runtime)
        setattr(runtime, "_extension_runtime", extension_runtime)
    else:
        setattr(runtime, "mcp_runtime", None)
    return runtime


def _create_host(workspace: Path) -> SessionHost:
    def runtime_factory(target_workspace: Path, record, lifecycle_subscribers=None):
        agent = AgentRuntime(
            llm_client=NoopLLMClient(),
            tool_registry=ToolRegistry(target_workspace),
            session_store=SessionStore(target_workspace / "sessions"),
            session_id=record.id,
            system_prompt=record.system_prompt,
            confirm_callback=lambda _name, _args: True,
            require_plan_approval=False,
        )
        agent.restore_session_record(record, emit_event=False)
        for subscriber in lifecycle_subscribers or []:
            agent.subscribe(subscriber)
        return agent

    return SessionHost(
        runtime_factory=runtime_factory,
        session_store_factory=lambda target_workspace: SessionStore(target_workspace / "sessions"),
        pending_action_store_factory=lambda target_workspace: PendingActionStore(target_workspace / "pending"),
        session_defaults_factory=lambda _target_workspace: {"system_prompt": "system", "model": ModelConfig()},
        checkpoint_store_factory=lambda target_workspace: CheckpointStore(target_workspace / "checkpoints"),
    )


def _init_git_repo(workspace: Path) -> None:
    subprocess.run(["git", "init"], cwd=workspace, check=True, capture_output=True, text=True)
    subprocess.run(["git", "config", "user.email", "bench@example.com"], cwd=workspace, check=True, capture_output=True, text=True)
    subprocess.run(["git", "config", "user.name", "Benchmark User"], cwd=workspace, check=True, capture_output=True, text=True)
    subprocess.run(["git", "add", "."], cwd=workspace, check=True, capture_output=True, text=True)
    subprocess.run(["git", "commit", "-m", "fixture"], cwd=workspace, check=True, capture_output=True, text=True)


def _planner_write_file(workspace: Path, task: BenchmarkTask, mode: str) -> ModeResult:
    runtime = _create_runtime(
        workspace,
        llm_client=ToolPlanLLMClient("write_file", {"path": "benchmark_write.txt", "content": "planner benchmark\n", "apply": True}),
        require_plan_approval=(mode == "pp-echo"),
    )
    events = runtime.prompt(task.prompt)
    target = workspace / "benchmark_write.txt"
    blocked = int(runtime.state.pending_plan_token is not None and not target.exists())
    if runtime.state.pending_plan_token:
        runtime.approve_pending_plan(runtime.state.pending_plan_token)
    return ModeResult(
        mode=mode,
        success=True,
        metrics={
            "approval_block_rate": float(blocked),
            "unsafe_write_before_approval": float(target.exists() and blocked == 0),
            "proxy_context_tokens": float(estimate_messages(runtime._messages_for_model(), runtime.tool_registry.openapi_specs())),
        },
        details={"event_count": len(events), "file_exists_after_run": target.exists()},
    )


def _planner_edit_file(workspace: Path, task: BenchmarkTask, mode: str) -> ModeResult:
    diff = "<<<<<<< SEARCH\nold value\n=======\nnew value\n>>>>>>> REPLACE"
    runtime = _create_runtime(
        workspace,
        llm_client=ToolPlanLLMClient("edit_file", {"path": "draft.txt", "diff": diff, "apply": True}),
        require_plan_approval=(mode == "pp-echo"),
    )
    events = runtime.prompt(task.prompt)
    target = workspace / "draft.txt"
    current = target.read_text(encoding="utf-8")
    blocked = int(runtime.state.pending_plan_token is not None and "new value" not in current)
    if runtime.state.pending_plan_token:
        runtime.approve_pending_plan(runtime.state.pending_plan_token)
    updated = target.read_text(encoding="utf-8")
    return ModeResult(
        mode=mode,
        success=True,
        metrics={
            "approval_block_rate": float(blocked),
            "unsafe_write_before_approval": float("new value" in current and blocked == 0),
            "proxy_context_tokens": float(estimate_messages(runtime._messages_for_model(), runtime.tool_registry.openapi_specs())),
        },
        details={"event_count": len(events), "updated_after_completion": "new value" in updated},
    )


def _planner_shell(workspace: Path, task: BenchmarkTask, mode: str) -> ModeResult:
    runtime = _create_runtime(
        workspace,
        llm_client=ToolPlanLLMClient(
            "run_shell",
            {"command": "Set-Content -LiteralPath shell_result.txt -Value 'shell benchmark'", "apply": True},
            final_text="shell complete",
        ),
        require_plan_approval=(mode == "pp-echo"),
    )
    events = runtime.prompt(task.prompt)
    target = workspace / "shell_result.txt"
    blocked = int(runtime.state.pending_plan_token is not None and not target.exists())
    if runtime.state.pending_plan_token:
        runtime.approve_pending_plan(runtime.state.pending_plan_token)
    return ModeResult(
        mode=mode,
        success=True,
        metrics={
            "approval_block_rate": float(blocked),
            "unsafe_write_before_approval": float(target.exists() and blocked == 0),
            "proxy_context_tokens": float(estimate_messages(runtime._messages_for_model(), runtime.tool_registry.openapi_specs())),
        },
        details={"event_count": len(events), "shell_output_exists": target.exists()},
    )


def _seed_host_session(host: SessionHost, workspace: Path) -> str:
    runtime = host.create_session(workspace)
    store = SessionStore(workspace / "sessions")
    record = store.load(runtime.session_id)
    record.messages = [
        ChatMessage(role="user", content=[TextPart(text="u1")], timestamp=1.0),
        ChatMessage(role="assistant", content=[TextPart(text="a1")], timestamp=2.0),
        ChatMessage(role="user", content=[TextPart(text="u2")], timestamp=3.0),
        ChatMessage(role="assistant", content=[TextPart(text="a2")], timestamp=4.0),
    ]
    store.save(record)
    return runtime.session_id


def _safe_rewind_workspace(workspace: Path, task: BenchmarkTask, mode: str) -> ModeResult:
    _init_git_repo(workspace)
    host = _create_host(workspace)
    session_id = _seed_host_session(host, workspace)
    checkpoint = host.create_checkpoint(workspace, session_id=session_id, reason="before-change")
    (workspace / "note.txt").write_text("changed\n", encoding="utf-8")
    if mode == "pp-echo":
        result = host.rewind_safe(workspace, session_id, checkpoint_id=checkpoint.checkpoint_id, mode="workspace_only")
        restored = int((workspace / "note.txt").read_text(encoding="utf-8") == "v1\n" and result.restored_workspace)
    else:
        restored = 0
    return ModeResult(mode=mode, success=True, metrics={"rewind_restore_success_rate": float(restored)}, details={"file_content": (workspace / "note.txt").read_text(encoding="utf-8")})


def _safe_rewind_conversation(workspace: Path, task: BenchmarkTask, mode: str) -> ModeResult:
    _init_git_repo(workspace)
    host = _create_host(workspace)
    session_id = _seed_host_session(host, workspace)
    checkpoint = host.create_checkpoint(workspace, session_id=session_id, reason="before-change")
    (workspace / "note.txt").write_text("dirty\n", encoding="utf-8")
    if mode == "pp-echo":
        result = host.rewind_safe(workspace, session_id, checkpoint_id=checkpoint.checkpoint_id, mode="conversation_only", message_count=0)
        restored = int(result.restored_conversation and not result.restored_workspace and result.session_id != session_id)
    else:
        restored = 0
    return ModeResult(mode=mode, success=True, metrics={"rewind_restore_success_rate": float(restored)}, details={"workspace_preserved": (workspace / "note.txt").read_text(encoding="utf-8") == "dirty\n"})


def _safe_rewind_full(workspace: Path, task: BenchmarkTask, mode: str) -> ModeResult:
    _init_git_repo(workspace)
    host = _create_host(workspace)
    session_id = _seed_host_session(host, workspace)
    checkpoint = host.create_checkpoint(workspace, session_id=session_id, reason="before-change")
    (workspace / "note.txt").write_text("v2\n", encoding="utf-8")
    if mode == "pp-echo":
        result = host.rewind_safe(workspace, session_id, checkpoint_id=checkpoint.checkpoint_id, mode="conversation_and_workspace", message_count=0)
        restored = int(result.restored_conversation and result.restored_workspace and (workspace / "note.txt").read_text(encoding="utf-8") == "v1\n")
    else:
        restored = 0
    return ModeResult(mode=mode, success=True, metrics={"rewind_restore_success_rate": float(restored)}, details={"file_content": (workspace / "note.txt").read_text(encoding="utf-8")})


def _session_fork_integrity(workspace: Path, task: BenchmarkTask, mode: str) -> ModeResult:
    host = _create_host(workspace)
    session_id = _seed_host_session(host, workspace)
    if mode == "pp-echo":
        forked = host.fork_session(workspace, session_id)
        tree = host.get_tree(workspace, session_id=session_id)
        integrity = int(any(child.get("id") == forked.session_id for child in tree.children))
    else:
        integrity = 0
    return ModeResult(mode=mode, success=True, metrics={"session_branch_integrity": float(integrity)}, details={"session_id": session_id})


def _session_rewind_integrity(workspace: Path, task: BenchmarkTask, mode: str) -> ModeResult:
    runtime = _create_runtime(workspace, llm_client=EchoLLMClient(), require_plan_approval=False)
    runtime.prompt("first")
    runtime.prompt("second")
    host = _create_host(workspace)
    if mode == "pp-echo":
        rewound = host.rewind_session(workspace, runtime.session_id, turn_count=1)
        tree = host.get_tree(workspace, session_id=rewound.session_id)
        integrity = int(bool(tree.current) and tree.current.get("parent_id") == runtime.session_id)
    else:
        integrity = 0
    return ModeResult(mode=mode, success=True, metrics={"session_branch_integrity": float(integrity)}, details={"source_session": runtime.session_id})


def _session_tree_integrity(workspace: Path, task: BenchmarkTask, mode: str) -> ModeResult:
    runtime = _create_runtime(workspace, llm_client=EchoLLMClient(), require_plan_approval=False)
    runtime.prompt("first")
    runtime.prompt("second")
    store = SessionStore(workspace / "sessions")
    record = store.load(runtime.session_id)
    turns = [item for item in record.turn_nodes if item.status == "committed"]
    if mode == "pp-echo" and turns:
        host = _create_host(workspace)
        navigated = host.navigate_tree(workspace, runtime.session_id, turns[0].id)
        tree = host.get_tree(workspace, session_id=runtime.session_id)
        integrity = int(tree.turn_focus is not None and navigated.active_head_id == turns[0].id)
    else:
        integrity = 0
    return ModeResult(mode=mode, success=True, metrics={"session_branch_integrity": float(integrity)}, details={"turn_count": len(turns)})


def _write_fetch_config(workspace: Path) -> None:
    project_dir = workspace / ".pp-agent"
    project_dir.mkdir(parents=True, exist_ok=True)
    (project_dir / "config.json").write_text(json.dumps({"capabilities": {"mcp": {"enable": True}}}), encoding="utf-8")
    (project_dir / "mcp.json").write_text(
        json.dumps(
            {
                "servers": [
                    {
                        "name": "fetch",
                        "description": "Community standard MCP server for fetching web pages as HTML, text, markdown, JSON, and readable article content.",
                        "transport": "memory",
                        "intent_tags": ["web", "url", "fetch", "article", "website", "link"],
                        "auto_match_examples": ["fetch this url", "summarize this webpage", "read this link"],
                    }
                ]
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )


def _mcp_no_match(workspace: Path, task: BenchmarkTask, mode: str) -> ModeResult:
    _write_fetch_config(workspace)
    events: list[str] = []
    runtime = _create_runtime(workspace, llm_client=EchoLLMClient(), enable_mcp=True, transport_factory=lambda _config: FetchTrackingClient(events))
    if mode == "baseline":
        runtime.mcp_runtime.ensure_discovered()
    messages = runtime.mcp_runtime.transform_context(
        type("State", (), {"messages": [ChatMessage(role="user", content=[TextPart(text=task.prompt)], timestamp=0)]})(),
        [ChatMessage(role="system", content=[TextPart(text="base")], timestamp=0)],
    )
    connections = float(events.count("initialize"))
    return ModeResult(
        mode=mode,
        success=True,
        metrics={
            "mcp_unneeded_connection_count": connections,
            "mcp_match_activation_rate": float(runtime.mcp_runtime.status()["last_match"] != {}),
        },
        details={"message_count": len(messages), "events": list(events)},
    )


def _mcp_url_match(workspace: Path, task: BenchmarkTask, mode: str) -> ModeResult:
    _write_fetch_config(workspace)
    events: list[str] = []
    runtime = _create_runtime(workspace, llm_client=EchoLLMClient(), enable_mcp=True, transport_factory=lambda _config: FetchTrackingClient(events))
    if mode == "baseline":
        runtime.mcp_runtime.ensure_discovered()
    messages = runtime.mcp_runtime.transform_context(
        type("State", (), {"messages": [ChatMessage(role="user", content=[TextPart(text=task.prompt)], timestamp=0)]})(),
        [ChatMessage(role="system", content=[TextPart(text="base")], timestamp=0)],
    )
    matched = runtime.mcp_runtime.status()["last_match"]
    return ModeResult(
        mode=mode,
        success=True,
        metrics={
            "mcp_unneeded_connection_count": float(max(0, events.count("initialize") - 1)),
            "mcp_match_activation_rate": float(matched.get("matched_server") == "fetch"),
        },
        details={"message_count": len(messages), "events": list(events), "last_match": matched},
    )


def _mcp_keyword_match(workspace: Path, task: BenchmarkTask, mode: str) -> ModeResult:
    return _mcp_url_match(workspace, task, mode)


def _long_payload(index: int) -> str:
    return (f"benchmark compaction turn {index} " + ("deterministic-payload-" * 30)).strip()


def _compaction_trigger(workspace: Path, task: BenchmarkTask, mode: str) -> ModeResult:
    compact_after = 4 if mode == "pp-echo" else 999
    runtime = _create_runtime(workspace, llm_client=EchoLLMClient(), compact_after_messages=compact_after, max_context_messages=50)
    captured: list[AgentEvent] = []
    runtime.subscribe(captured.append)
    for index in range(8):
        runtime.prompt(_long_payload(index))
    compacted = int(runtime.state.compaction.summarized_message_count > 0)
    return ModeResult(
        mode=mode,
        success=True,
        metrics={
            "compaction_trigger_rate": float(compacted),
            "proxy_context_tokens": float(estimate_messages(runtime._messages_for_model(), runtime.tool_registry.openapi_specs())),
        },
        details={"summary_length": len(runtime.state.compaction.summary), "event_types": [event.type for event in captured]},
    )


def _compaction_reduction(workspace: Path, task: BenchmarkTask, mode: str) -> ModeResult:
    compact_after = 4 if mode == "pp-echo" else 999
    runtime = _create_runtime(workspace, llm_client=EchoLLMClient(), compact_after_messages=compact_after, max_context_messages=50)
    for index in range(10):
        runtime.prompt(_long_payload(index))
    context_tokens = float(estimate_messages(runtime._messages_for_model(), runtime.tool_registry.openapi_specs()))
    raw_tokens = float(estimate_messages([ChatMessage(role="system", content=[TextPart(text=runtime.state.system_prompt)], timestamp=time.time()), *runtime.state.messages], runtime.tool_registry.openapi_specs()))
    reduction = 0.0 if raw_tokens == 0 else max(0.0, 1.0 - (context_tokens / raw_tokens))
    return ModeResult(
        mode=mode,
        success=True,
        metrics={
            "context_size_reduction_ratio": reduction,
            "proxy_context_tokens": context_tokens,
        },
        details={"raw_proxy_tokens": raw_tokens, "summary_length": len(runtime.state.compaction.summary)},
    )


def _compaction_persisted(workspace: Path, task: BenchmarkTask, mode: str) -> ModeResult:
    compact_after = 4 if mode == "pp-echo" else 999
    runtime = _create_runtime(workspace, llm_client=EchoLLMClient(), compact_after_messages=compact_after, max_context_messages=50)
    for index in range(8):
        runtime.prompt(_long_payload(index))
    stored = SessionStore(workspace / "sessions").load(runtime.session_id)
    summarized = float(stored.compaction.summarized_message_count)
    return ModeResult(
        mode=mode,
        success=True,
        metrics={
            "compaction_trigger_rate": float(summarized > 0),
            "proxy_context_tokens": float(estimate_messages(runtime._messages_for_model(), runtime.tool_registry.openapi_specs())),
        },
        details={"summarized_message_count": summarized},
    )


_SCENARIOS = {
    "planner_write_file": _planner_write_file,
    "planner_edit_file": _planner_edit_file,
    "planner_shell": _planner_shell,
    "safe_rewind_workspace": _safe_rewind_workspace,
    "safe_rewind_conversation": _safe_rewind_conversation,
    "safe_rewind_full": _safe_rewind_full,
    "session_fork_integrity": _session_fork_integrity,
    "session_rewind_integrity": _session_rewind_integrity,
    "session_tree_integrity": _session_tree_integrity,
    "mcp_no_match": _mcp_no_match,
    "mcp_url_match": _mcp_url_match,
    "mcp_keyword_match": _mcp_keyword_match,
    "compaction_trigger": _compaction_trigger,
    "compaction_reduction": _compaction_reduction,
    "compaction_persisted": _compaction_persisted,
}


def _average(values: list[float]) -> float:
    if not values:
        return 0.0
    return sum(values) / len(values)


def _mode_metric_for_tasks(result: BenchmarkSuiteResult, metric_name: str, mode: str, task_ids: list[str]) -> list[float]:
    values: list[float] = []
    for task_id in task_ids:
        mode_result = result.mode_result(task_id, mode)
        if mode_result is None:
            continue
        if metric_name in mode_result.metrics:
            values.append(float(mode_result.metrics[metric_name]))
    return values


def _aggregate_metrics(result: BenchmarkSuiteResult) -> dict[str, float]:
    planner_pp = result.mode_metrics("approval_block_rate", "pp-echo")
    planner_base_unsafe = result.mode_metrics("unsafe_write_before_approval", "baseline")
    rewind_pp = result.mode_metrics("rewind_restore_success_rate", "pp-echo")
    rewind_base = result.mode_metrics("rewind_restore_success_rate", "baseline")
    branching_pp = result.mode_metrics("session_branch_integrity", "pp-echo")
    mcp_unneeded_pp = _mode_metric_for_tasks(result, "mcp_unneeded_connection_count", "pp-echo", ["mcp_lazy.no_match"])
    mcp_unneeded_base = _mode_metric_for_tasks(result, "mcp_unneeded_connection_count", "baseline", ["mcp_lazy.no_match"])
    mcp_activation_pp = _mode_metric_for_tasks(result, "mcp_match_activation_rate", "pp-echo", ["mcp_lazy.url_match", "mcp_lazy.keyword_match"])
    compaction_pp = _mode_metric_for_tasks(result, "compaction_trigger_rate", "pp-echo", ["context_compaction.trigger"])
    context_reduction_pp = _mode_metric_for_tasks(result, "context_size_reduction_ratio", "pp-echo", ["context_compaction.reduction"])
    context_tokens_pp = _mode_metric_for_tasks(result, "proxy_context_tokens", "pp-echo", ["context_compaction.reduction"])
    context_tokens_base = _mode_metric_for_tasks(result, "proxy_context_tokens", "baseline", ["context_compaction.reduction"])
    return {
        "approval_block_rate_pp_echo": _average(planner_pp),
        "unsafe_write_before_approval_baseline": _average(planner_base_unsafe),
        "rewind_restore_success_rate_pp_echo": _average(rewind_pp),
        "rewind_restore_success_rate_baseline": _average(rewind_base),
        "session_branch_integrity_pp_echo": _average(branching_pp),
        "mcp_unneeded_connection_count_pp_echo": _average(mcp_unneeded_pp),
        "mcp_unneeded_connection_count_baseline": _average(mcp_unneeded_base),
        "mcp_match_activation_rate_pp_echo": _average(mcp_activation_pp),
        "compaction_trigger_rate_pp_echo": _average(compaction_pp),
        "context_size_reduction_ratio_pp_echo": _average(context_reduction_pp),
        "proxy_context_tokens_pp_echo": _average(context_tokens_pp),
        "proxy_context_tokens_baseline": _average(context_tokens_base),
    }


def _headline_results(result: BenchmarkSuiteResult) -> list[str]:
    metrics = result.aggregate_metrics
    planner_rate = metrics["approval_block_rate_pp_echo"] * 100.0
    unsafe_rate = metrics["unsafe_write_before_approval_baseline"] * 100.0
    rewind_rate = metrics["rewind_restore_success_rate_pp_echo"] * 100.0
    mcp_saved = max(0.0, metrics["mcp_unneeded_connection_count_baseline"] - metrics["mcp_unneeded_connection_count_pp_echo"])
    compaction_reduction = metrics["context_size_reduction_ratio_pp_echo"] * 100.0
    return [
        f"Planner approval blocked risky mutations before execution in {planner_rate:.0f}% of gating tasks, while the internal baseline mutated immediately in {unsafe_rate:.0f}%.",
        f"Safe rewind recovered the requested workspace and conversation state in {rewind_rate:.0f}% of rewind tasks, versus 0% in the no-recovery baseline.",
        f"Lazy MCP routing avoided {mcp_saved:.2f} unnecessary server initializations per task on average while still activating the matched web-fetch path when needed.",
        f"Context compaction reduced normalized prompt size by {compaction_reduction:.0f}% on average in long-dialogue tasks.",
    ]







