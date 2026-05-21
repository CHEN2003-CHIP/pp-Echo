# Workflows

<!-- pp-echo-detail-memory:begin -->
9-96ec-d910f764b7a1 turn=turn-3

### Subagent orchestration workflow

To use subagents, trigger explicit handoff with @subagent in chat or use the orchestrate_agents tool for parallel read-only analysis. Built-in specs include repo-researcher, change-reviewer, test-investigator, api-scout, memory-scout, implementation-planner, and code-worker. Child execution forks a session, narrows tools, runs a constrained prompt, and returns a summary.

Evidence: README.md section 'Subagent Progress' and 'Core Workflows > 1A. Explicit subagent handoff'. Lists specific built-in child specs and describes the narrow, bounded nature of current subagent support.

Source: session=e82d84e7-f854-4e9a-b08a-9af4cd1298df turn=turn-1

### README.md Smoke Test Line Replacement Protocol

When replacing the final line of README.md with a specific smoke test string, first verify the current ending content. If the edit tool is unavailable in the current session (e.g., read-only api-scout), identify the exact target line and recommend the host agent perform the replacement to ensure atomicity.

Evidence: The task required replacing the last line of README.md. The api-scout session had only read tools (read_file, list_files, search_text, grep_code) and could not write. The solution involved identifying the target location and recommending the host apply the change.

Source: session=756352f6-2199-4b26-b27a-a13dc9f75045 turn=turn-2

### README.md smoke test line replacement pattern

When updating the README.md smoke test section, replace the entire existing description line (including bold formatting and command examples) with a concise single-line identifier. Ensure no extra blank lines or trailing content are added.

Evidence: The task required replacing '**Smoke test**: `python -m pp_agent.cli.main run "Hello"` should return a greeting within 10 seconds.' with 'pp-Echo isolated worktree smoke test'.

Source: session=ec43c49b-8039-47d7-bcc9-bf396ddd96b4 turn=turn-2

### orchestrate_agents for code changes

Use the orchestrate_agents tool with workflow=code_change to handle file edits. Do not call edit_file/write_file directly; instead, delegate to subagents (e.g., code-worker) via orchestration to ensure proper review and staged changes.

Evidence: User instruction: '不要直接调用 edit_file/write_file。请必须使用 orchestrate_agents。workflow=code_change'. The turn shows multiple attempts where direct edits failed or were incorrect, while orchestrate_agents coordinated subagents to identify and correct the README.md content.

Source: session=e82d84e7-f854-4e9a-b08a-9af4cd1298df turn=turn-5

### Subagent Execution Constraints

When acting as a repo-researcher subagent, strictly adhere to read-only constraints unless explicitly granted write permissions. Do not expand scope or call spawn_subagent. Output must follow a specific summary format (Summary, Findings, Recommended next action, Files/paths inspected, Confidence).

Evidence: Constraints specified: 'capability profile summary... workspace=read_only', 'Never call spawn_subagent', 'Return summary output only'.

Source: session=9e20b4b7-1238-4995-b219-cf371abfe128 turn=turn-1

### Verification of Prior Agent Claims

When a prior subagent claims a file creation task is complete, verify the actual file state using read-only tools before concluding the task, especially when current toolset lacks write capabilities.

Evidence: Prior agent api-scout claimed success; implementation-planner verified tool constraints and initiated read_file check to confirm state.

Source: session=63649f02-5bf6-40fd-a812-9f3d74d7f6c4 turn=turn-1

### Handling Capability Conflicts in Subagent Sessions

If a task requires a capability not present in the current toolset (e.g., creating files without write_file), do not attempt workarounds or assume hidden permissions. Instead, verify the current tool list against the task requirements and escalate or request configuration changes if the objective cannot be met.

Evidence: The change-reviewer agent verified the toolset, found no write capabilities, and recommended escalating to a supervisor rather than failing silently or assuming incorrect permissions.

Source: session=b5cd89ec-629d-4923-b584-b49d9cd3f0a9 turn=turn-1

### Read-Only Agent Limitation Handling

When an agent operating in read-only mode (with tools like read_file, list_files, search_text, grep_code) is tasked with file creation, it must identify the tool mismatch and report that external write capabilities are required rather than attempting to execute the write or expanding scope.

Evidence: The agent correctly identified that its available tools were read-only and recommended a system-level write operation instead of failing silently or trying to bypass constraints.

Source: session=01c97bc6-f97b-416d-a11c-5cf47e8aa340 turn=turn-1

### Orchestration Requirement for Code Changes

When performing code changes or file creation tasks, the agent must use the 'orchestrate_agents' tool instead of directly calling 'edit_file' or 'write_file'. This is a mandatory constraint for the 'code_change' workflow.

Evidence: Trusted instructions explicitly state: '不要直接调用 edit_file/write_file。请必须使用 orchestrate_agents。workflow=code_change'

Source: session=4461e190-7d78-41ed-8232-bdbdc9f84096 turn=turn-1

### Orchestration Requirement for File Creation

When creating files or performing code changes, do not call edit_file/write_file directly. Instead, use the orchestrate_agents tool with the code_change workflow.

Evidence: Task instructions explicitly state: '不要直接调用 edit_file/write_file。请必须使用 orchestrate_agents。workflow=code_change'

Source: session=7d5337cf-656b-4db2-87f5-70bd3fed6b23 turn=turn-1

### Toolset Mismatch in Orchestrated Workflows

When a task mandates the use of 'orchestrate_agents' for code changes, direct file editing tools (edit_file/write_file) are forbidden. If the current agent session lacks the orchestration capability, the task cannot be completed and must be escalated rather than bypassed.

Evidence: Prior subagent manifests confirmed toolset mismatch: allow_edits=true conflicts with workspace=read_only and missing orchestrate_agents. Instructions explicitly forbid direct calls to edit_file/write_file when orchestrate_agents is required.

Source: session=2f358e6e-1dbe-44e4-911b-a7f54caffb1b turn=turn-1

### orchestrate_agents code_change workflow with read-only constraints

When `allow_edits=true` is set but the environment is restricted to read-only tools (no `edit_file`, `write_file`, or `orchestrate_agents`), the system falls back to a deterministic isolated worktree patch mechanism. The `code-worker` subagent can create files in an isolated context, which are then staged as patches for review.

Evidence: The task required creating a file via `orchestrate_agents`. Despite the tool being unavailable due to `workspace=read_only`, the `code-worker` agent successfully created the file in an isolated worktree and produced a staged patch artifact.

Source: session=ee609e8b-33c6-4a74-842c-8aac623ed3ab turn=turn-1

### Handling Unfulfillable Write Requests in Read-Only Sessions

If a task requires creating files using orchestrate_agents but the current agent only has read-only tools (read_file, list_files, search_text, grep_code), do not attempt direct edits. Instead, summarize the tool limitation and recommend escalating to an agent with orchestration capabilities or enabling write permissions.

Evidence: The assistant's output explicitly states: 'Escalate to agent with orchestrate_agents capability or enable write permissions in the session. Current subagent cannot proceed.' This was based on consistent findings across prior manifests regarding tool availability.

Source: session=a174dc86-d0a3-447c-8105-e88ec2612ae0 turn=turn-1

### Project Startup Scripts

The project uses specific batch scripts for launching different components: start-agent.bat for the Agent, start-web.bat for the Web service, and echo-cli.bat for CLI operations.

Evidence: Presence of start-agent.bat, start-web.bat, and echo-cli.bat in the directory listing.

Source: session=8c695242-be85-4232-aab5-093b1d973659 turn=turn-5

### File Creation via Orchestration

When a task requires file creation or modification but the current agent session has read-only constraints, do not attempt direct edits. Instead, use the `orchestrate_agents` tool with a `code_change` workflow to delegate the write operation to an agent with appropriate permissions.

Evidence: The user explicitly instructed 'Do not directly call edit_file/write_file' and 'Must use orchestrate_agents'. The agent's capability profile confirmed it only had read tools (read_file, list_files, etc.) and lacked orchestration capabilities.

Source: session=b1b826c9-027b-410e-b7a9-30f3ea5d0285 turn=turn-1

### Handling Unexecutable Write Tasks via Read-Only Agents

When a subagent with read-only capabilities receives a task requiring file creation or modification via `orchestrate_agents`, it must identify the missing tooling and recommend escalation rather than attempting partial execution or ignoring constraints.

Evidence: The implementation-planner identified the gap between the task requirement (`orchestrate_agents`, `allow_edits=true`) and its actual environment (read-only tools), concluding that escalation is the only valid next action.

Source: session=9af0471a-460a-4fec-a2fa-a30c39f97547 turn=turn-1

### Isolated worktree patch creation and approval process

When using orchestrate_agents for code changes, a patch artifact is staged in an isolated worktree. The change is not applied to the main workspace until explicitly approved via the Approval panel or approve_pending_action.

Evidence: Agent logs showing 'staged only, not applied to the main workspace' and instructions to 'use the Approval panel or approve_pending_action to apply the patch'.

Source: session=e693a39c-603b-48b6-905f-e378106c6049 turn=turn-1

### Patch Artifact Application Workflow

When a subagent creates files in an isolated worktree and stages a patch artifact, the reviewer agent must verify the staged action and recommend applying the specific patch artifact to finalize changes if the reviewer lacks write permissions.

Evidence: The code-worker created docs/web-smoke-check.md and staged a patch artifact. The change-reviewer, limited to read-only tools, identified the artifact path and recommended applying it via apply_patch_artifact.

Source: session=56171e59-aec0-40fe-936f-b1c3298489f2 turn=turn-2

### Code Change via Orchestration and Staging

When using `orchestrate_agents` for code changes, the system may produce a staged patch artifact in an isolated worktree. The change is not applied to the main workspace until explicitly approved via the Approval panel or `approve_pending_action`.

Evidence: Summary indicates 'Status: staged only, not applied to the main workspace' and instructions to use Approval panel or `approve_pending_action`.

Source: session=9f436abf-e99f-4a47-b62c-39dbd25f7602 turn=turn-2

### Browser Tool Verification Procedure

A standardized procedure to verify browser tool availability using a data URL, input simulation, click interaction, and screenshot capture without requiring user approval.

Evidence: The turn demonstrates a complete workflow: navigating a data URL, reading state, typing text, clicking a button to trigger an event, verifying the DOM change, and capturing a screenshot.

Source: session=7a1a9663-d84a-4273-833e-3530e3162560 turn=turn-1

### MCP Integration for Coding Agents

There is a strong trend towards integrating Model Context Protocol (MCP) into coding agents. Projects like 'ChromeDevTools/chrome-devtools-mcp' and 'HKUDS/CLI-Anything' demonstrate the shift towards making all software agent-native through standardized context protocols.

Evidence: Trending items explicitly mention 'MCP Registry', 'Chrome DevTools for coding agents', and 'Making ALL Software Agent-Native'.

Source: session=99f5237f-850b-4b14-a5f2-fe2cf15b7de1 turn=turn-7
<!-- pp-echo-detail-memory:end -->
