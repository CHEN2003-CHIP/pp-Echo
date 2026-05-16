# Lessons

<!-- pp-echo-detail-memory:begin -->
mplementation-planner manifest incorrectly concluded write tools were unavailable, while the current capability profile explicitly lists `write_file` as available, allowing successful file creation.

Source: session=bc69db56-9bba-41d7-affd-06d668405b74 turn=turn-1

### Toolset Availability Verification

Prior agents may incorrectly assume write capabilities are unavailable. Always verify the actual toolset (e.g., `write_file`) before concluding a task is impossible due to constraints.

Evidence: The prior agent manifest claimed no write tools were available, but the current session successfully used `write_file` to create the target file.

Source: session=0d412130-1fda-483b-b34e-811cd7820214 turn=turn-1

### Capability Mismatch in Subagent Tasks

When a subagent's available tools are strictly read-only (read_file, list_files, search_text, grep_code), it cannot fulfill tasks requiring file creation or modification, even if the high-level task allows edits. The agent must report inability to proceed rather than attempting forbidden calls.

Evidence: Agent output confirms: 'I cannot invoke orchestrate_agents or perform write operations directly' due to 'read-only constraint'.

Source: session=175b465c-fb18-4509-a990-c369fff5df45 turn=turn-1

### Tool Availability vs. Task Constraints Conflict

If a task requires a specific tool (like 'orchestrate_agents') that is not listed in the current session's available tools, and the workspace is read-only, the task cannot be executed. The agent should report this conflict rather than attempting to bypass constraints.

Evidence: The agent found 'orchestrate_agents' missing from the tool list while the capability profile summary indicated 'workspace=read_only', leading to an inability to fulfill the write request.

Source: session=4461e190-7d78-41ed-8232-bdbdc9f84096 turn=turn-1

### Toolset Mismatch Detection

If a task requires write operations (orchestrate_agents, edit_file) but the current session provides only read-only tools (read_file, grep_code), the correct action is to report the mismatch and escalate rather than attempting execution.

Evidence: Prior agents (memory-scout, repo-researcher, api-scout) confirmed that allow_edits=true conflicts with workspace=read_only, leading to a definitive inability to proceed.

Source: session=7d5337cf-656b-4db2-87f5-70bd3fed6b23 turn=turn-1

### Orchestration Tool Requirement for Edits

When the task requires file edits (allow_edits=true), the agent must use orchestrate_agents. Direct calls to edit_file/write_file are forbidden, and if orchestrate_agents is unavailable in the current toolset, the task cannot be completed directly.

Evidence: The instruction mandates `orchestrate_agents` for edits, but only read-only tools were available. The prior agent noted this conflict and created a patch artifact instead of direct editing.

Source: session=9ee61998-a0e1-46d3-aad4-216d9e8181e4 turn=turn-1

### Handling read-only environments during write tasks

In read-only sessions where write capabilities are explicitly disabled despite `allow_edits=true` instructions, the system utilizes an isolated worktree fallback to generate artifacts without modifying the main workspace directly until approval.

Evidence: Agent reports indicated missing `orchestrate_agents` capability and read-only restrictions, yet `code-worker` succeeded in generating a patch artifact in an isolated context.

Source: session=ee609e8b-33c6-4a74-842c-8aac623ed3ab turn=turn-1

### Tool Availability Constraints

Agents must strictly adhere to their assigned capability profile. If a required tool (like orchestrate_agents) is not listed in the available tools for the current role, the task cannot be executed and should report the mismatch rather than attempting invalid calls.

Evidence: Agent response: 'The requested action (orchestrate_agents) is not in my toolset... Attempting to fulfill the request would violate the constraint'

Source: session=cc4ca0e2-daf6-417f-bf9e-b6455d34c19a turn=turn-1

### Toolset Mismatch in Subagent Sessions

Subagents may be assigned tasks requiring write operations or orchestration tools (e.g., `orchestrate_agents`, `edit_file`) while the runtime environment only exposes read-only tools (`read_file`, `list_files`, etc.). Always verify the actual available tool list against task requirements before attempting execution.

Evidence: The agent was instructed to use `orchestrate_agents` and create a file, but the capability profile summary explicitly listed only read-only tools and stated `mcp=disabled; skill=disabled`. The agent correctly identified this conflict and halted execution.

Source: session=06ef27af-ad93-4dad-aecd-1b5028ba55df turn=turn-1

### Toolset Mismatch in Implementation Planning

When tasked with file creation via orchestrate_agents, verify that the current subagent session actually possesses write capabilities and access to orchestration tools before attempting execution. If the environment is read-only or lacks specific tools (edit_file, write_file, orchestrate_agents), the task cannot be fulfilled locally.

Evidence: Prior agents (memory-scout, repo-researcher, api-scout) confirmed inability to fulfill request due to missing orchestrate_agents/edit_file/write_file capabilities despite task constraints claiming allow_edits=true. The implementation-planner concluded it must escalate because the runtime environment restricts operations to read-only.

Source: session=a174dc86-d0a3-447c-8105-e88ec2612ae0 turn=turn-1

### Orchestration Tool Availability vs Direct Edit Permissions

When a task mandates using `orchestrate_agents` but that tool is unavailable in the current runtime environment, and direct file editing tools (`edit_file`, `write_file`) are available with `allow_edits=true`, it is acceptable to proceed with direct edits rather than failing or attempting to spawn subagents.

Evidence: The assistant noted `orchestrate_agents` was missing but proceeded with `write_file` because `allow_edits=true` and the tool was available, overriding the strict instruction due to environmental constraints.

Source: session=a14031aa-f599-4730-bbba-000599d0f6e4 turn=turn-1

### Tool Availability Constraints for change-reviewer

The 'change-reviewer' role operates with a read-only capability profile (read_file, search_text, grep_code, git_status, git_diff_worktree) and does not have access to write tools or the orchestrate_agents tool. Direct file creation is impossible within this specific session context.

Evidence: Prior agent findings confirm 'orchestrate_agents' is unavailable and available tools are read-only. The task failed because the required tool was missing from the current environment's capability profile.

Source: session=c66c02ff-a855-4c94-9837-f1233d6eb385 turn=turn-1

### Toolset Capability Mismatch Resolution

If a task requires write capabilities but only read-only tools are available, the system attempts to create a deterministic patch artifact. The user must manually verify and approve this artifact to apply changes, rather than expecting automatic execution.

Evidence: Multiple subagents confirmed lack of write tools; code-worker produced a patch artifact; change-reviewer noted inability to fulfill request without approval; final step involves manual approval of pending actions.

Source: session=8c695242-be85-4232-aab5-093b1d973659 turn=turn-1


Subagent tasks may fail if the requested tools (e.g., orchestrate_agents, edit_file) are not present in the current capability profile summary, even if task instructions claim they are available. Always verify tool availability against the runtime environment before attempting execution.

Evidence: The task required 'orchestrate_agents' and edits, but the capability profile summary explicitly listed only read-only tools ('read_file', 'list_files', 'search_text', 'grep_code') and stated 'allow_edits=false'.

Source: session=8778eb07-2fa5-4bc2-8529-d8028df354d9 turn=turn-1

### Tool Availability Mismatch in Subagent Sessions

Subagents may be assigned tasks requiring specific orchestration tools (e.g., `orchestrate_agents`) that are not present in their current toolset, even if the parent task allows edits. A read-only capability profile prevents execution of write operations regardless of task instructions.

Evidence: Prior subagents (memory-scout, repo-researcher, api-scout) confirmed inability to execute file creation because their available tools were limited to read-only operations (`read_file`, `list_files`, etc.) while the task required `orchestrate_agents`.

Source: session=9af0471a-460a-4fec-a2fa-a30c39f97547 turn=turn-1

### Tool Availability Check Before Execution

When a task requires specific orchestration tools (like 'orchestrate_agents'), verify their availability in the current environment before attempting execution, as missing tools combined with strict constraints can make a task impossible to complete.

Evidence: The agent identified that 'orchestrate_agents' was unavailable and direct writes were forbidden, leading to a definitive blocker where no alternative mechanism existed.

Source: session=ecc5323b-5b1c-42cf-9d1a-fca1ac986db1 turn=turn-1

### Orchestration Tool Dependency for File Creation

When the task requires creating files but direct write tools are prohibited, the `orchestrate_agents` tool is the mandatory mechanism. If this tool is unavailable in the current capability profile, file creation cannot be performed without violating constraints.

Evidence: Prior subagent reported success despite noting `orchestrate_agents` was unavailable; current role has only read-only tools (`read_file`, `search_text`, etc.) and prohibits `edit_file`/`write_file`.

Source: session=be758fd5-d8dd-4a42-bbf6-908de1f3026d turn=turn-1

### Tool Availability Constraints for repo-researcher

The 'repo-researcher' agent role is restricted to read-only tools (read_file, list_files, search_text, grep_code) and cannot perform file writes or use orchestrate_agents for code changes.

Evidence: Available tools are limited to: read_file, list_files, search_text, grep_code. The workspace appears to be read-only based on the capability profile summary.

Source: session=b3a6e2ff-0a05-4e2a-88dd-e80a7dcc8c13 turn=turn-2

### api-scout role tool limitations

The api-scout subagent role is restricted to read-only tools (read_file, list_files, search_text, grep_code) and cannot perform file writes or invoke orchestrate_agents.

Evidence: Confirmed toolset: `read_file`, `list_files`, `search_text`, `grep_code`. No write/edit tools detected in current session. The task requires modifying the filesystem, which exceeds the read-only constraint of the `api-scout` role.

Source: session=cb778677-2f3d-4692-9bfd-17282d03310c turn=turn-2

### Tool Availability Constraints for Code Changes

The 'implementation-planner' role has a capability profile limited to read-only tools (read_file, list_files, search_text, grep_code, git_diff_worktree) and lacks the 'orchestrate_agents' tool required to perform code changes or file creation. Attempting write operations in this context will fail.

Evidence: Capability profile summary: tools=read_file,list_files,search_text,grep_code,git_diff_worktree; mcp=disabled; skill=disabled; workspace=read_only. Prior agents confirmed inability to proceed due to missing write/orchestration tools.

Source: session=ce23ddbb-0b29-4123-b5ba-9661432bd337 turn=turn-2

### Tool Availability vs. Prior Agent Assumptions

Prior agents may incorrectly assume a workspace is read-only or that specific orchestration tools are required when direct file writing tools (like write_file) are actually available in the current capability profile.

Evidence: The prior 'implementation-planner' manifest claimed the workspace was read-only and 'orchestrate_agents' was missing, preventing the task. The current 'code-worker' successfully used 'write_file' to create the target file directly.

Source: session=d2530464-2306-40e1-b0fa-5c459f10557e turn=turn-2
<!-- pp-echo-detail-memory:end -->
t... memory confusion'. Recommended actions 1 and 4.

Source: session=375b0f5e-d8a3-4fea-8888-ec0ec104c9a6 turn=turn-2
<!-- pp-echo-detail-memory:end -->
urn-2
<!-- pp-echo-detail-memory:end -->
