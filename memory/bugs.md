# Bugs

<!-- pp-echo-detail-memory:begin -->
### Memory Context Overflow Risk in Long-Running Sessions

The current memory implementation lacks automatic token-based truncation or summarization, leading to potential context window overflow in long sessions. The system relies on fixed semantic similarity thresholds which may introduce noise.

Evidence: Findings A: 'Infinite growth' risk noted due to lack of auto-cleanup; 'Retrieval noise' from fixed thresholds.

Source: session=1108985f-6d4d-437a-8e3a-de37060bc4d4 turn=turn-2

### Memory Service Cold-Start Failure Mode

The MemoryService relies on hybrid retrieval (BM25 + Vector) which fails silently or throws exceptions if the index is uninitialized or empty. A defensive strategy must be implemented to handle cold-start scenarios by checking for index existence before search execution.

Evidence: Findings section 1.1: 'Cold start failure: If memory directory is empty... search may return empty results or throw exception'. Recommended action 1: 'Add empty index check and exception handling'.

Source: session=326b2ecb-9061-41a1-92a7-c162233d1356 turn=turn-2

### Subagent Orchestration Failure Pattern: Missing Summary Section

Repeated failures in multi-agent orchestration (orchestrate_agents) occurred because subagents (memory-scout, repo-researcher, api-scout) failed to generate a 'usable summary section' in their output. This indicates a potential issue with the subagent prompt engineering, output parsing logic, or the specific workflow definition requiring a structured summary that the current model/configuration cannot produce.

Evidence: Failures: memory-scout:failed | repo-researcher:failed | api-scout:failed; Reason: Subagent summary did not include a usable summary section.

Source: session=91c18298-91cd-4a8c-9df7-865320f5c9a2 turn=turn-2

### File Path Resolution Mismatch in Local Environment

Direct file reading attempts using absolute Windows paths (E:\Pycharm Project\pp-Echo\...) resulted in 'No such file or directory' errors. This suggests a mismatch between the tool's expected working directory context and the actual file system structure, or that the specified module files do not exist at the anticipated locations within the project hierarchy.

Evidence: tool:read_file: [Errno 2] No such file or directory: 'E:\Pycharm Project\pp_agent\memory\search.py' (and similar for service.py, registry.py, orchestration.py).

### Subagent Summary Validation and Parsing Logic

The pp-Echo subagent system validates output via `parse_subagent_output` (in `src/pp_agent/subagents/specs.py`) and `_validate_summary_text` (in `src/pp_agent/subagents/manager.py`). The parser supports both JSON and plain text formats, normalizing Markdown headings (e.g., `### 0. Summary`) to standard section keys. Validation enforces a 2500-character limit and requires non-empty fields for 'summary', 'findings', 'recommended_next_action', and 'confidence'. Failure results in `invalid_summary` if the model returns tool-result fallbacks, exceeds length limits, or omits required sections.

Evidence: Code in `src/pp_agent/subagents/specs.py` (`_normalize_section_heading`, `parse_subagent_output`) and `src/pp_agent/subagents/manager.py` (`_validate_summary_text`, `run_sync` logic). Test case `test_subagent_manager_accepts_markdown_heading_summary` confirms Markdown headings are accepted.

Source: session=c17904f7-ad01-43a5-aefe-c08724f1284d turn=turn-1

### Subagent Turn Limit Constraints in Parallel Orchestration

When orchestrating multiple sub-agents in parallel for deep analysis tasks, a low max_turns limit (e.g., 2) can cause premature termination if the task requires iterative reasoning or multi-step file inspection. This results in partial data collection and failed status for affected agents.

Evidence: repo-researcher and api-scout both failed with failure_kind 'turn_limit_reached' after exceeding max_turns=2 during the analysis of pp-Echo modules.

Source: session=941f6f6c-e8d9-4bc1-a043-73379a04c142 turn=turn-2

### Subagent Runtime Isolation Risks

SubagentRuntime uses separate memory spaces and UUID-based session tracking, but shared resource cleanup may not be atomic across all failure modes. File descriptor inheritance between parent/child processes requires auditing.

Evidence: Analysis of /src/runtime/subagent_runtime.py reveals potential non-atomic cleanup in failure scenarios and lack of explicit file descriptor isolation verification.

Source: session=29bafa53-e4b3-481c-9e2c-e82da7c33006 turn=turn-1

### README.md Smoke Test Line Specification

The README.md file requires a specific line 'pp-Echo isolated worktree smoke test' to be appended at the very end. Previous attempts failed by adding descriptive text or formatting (e.g., '**Smoke test**:') instead of the exact required string.

Evidence: Prior subagent manifest indicates an incorrect edit was staged ('**Smoke test**: ...') and the current review confirms the need for the exact text without additional content.

Source: session=42c21b52-5214-464d-a058-7388c244fcaa turn=turn-2

### Handling Staged Incorrect Edits in Read-Only Contexts

When a read-only agent (like change-reviewer) identifies a staged edit containing incorrect content, it cannot fix it directly. The workflow requires identifying the discrepancy and recommending a code-worker agent with edit_file capability to perform the correction.

Evidence: The assistant found a previous edit was staged but contained incorrect content and noted 'No tools available for editing' due to the read-only capability profile.

Source: session=1f179ac2-3e6e-430a-b8ca-a12a08607399 turn=turn-2

### Orchestration failure handling when tools lack write capability

In a multi-agent orchestration (workflow=code_change), agents may have conflicting views on tool availability. If an agent claims a file was created but subsequent agents verify that write tools are unavailable in their specific context, the overall operation fails without a patch artifact. This requires explicit failure reporting.

Evidence: Agent api-scout claimed creation, but implementation-planner and change-reviewer verified no write capabilities were available. Result: 'The orchestration completed but failed to produce an apply_patch_artifact'.

Source: session=94388b3f-62f8-4d38-8525-1fde68818ddb turn=turn-1

### Prior Agent Capability Assumption Error

A prior agent (code-worker) incorrectly assumed write capabilities were unavailable and failed to produce a patch artifact, yet claimed to have created the target file. The current agent (change-reviewer) has read-only constraints and must verify the actual state rather than trusting prior claims.

Evidence: Prior manifest states 'incorrectly concluded that write capabilities were unavailable' and 'produced no apply_patch_artifact', while claiming file creation. Current role tools are limited to read_file, search_text, grep_code, git_status, git_diff_worktree.

Source: session=7696b756-f793-4e00-85cc-17675faee509 turn=turn-1

### Handling failed patch artifacts in orchestrate_agents

If the orchestrate_agents workflow (specifically code_change) completes but the code-worker subagent fails to produce an isolated patch artifact, the system must report the task as FAILED instead of attempting to verify or create files directly.

Evidence: Assistant response: 'The orchestration has completed, but the code-worker subagent failed to produce an apply_patch_artifact... I cannot fall back to direct file editing... Status: FAILED'

Source: session=67678dcf-22f8-436d-854d-520d98d5dc1b turn=turn-1

### code_change workflow with allow_edits=true failure protocol

When workflow=code_change and allow_edits=true are set, direct calls to edit_file or write_file are prohibited. If orchestrate_agents fails to produce a patch artifact, the system must report the task as failed rather than falling back to direct file editing.

Evidence: Assistant response: 'Per the explicit instruction... direct calls to edit_file or write_file are prohibited... if no patch artifact is produced, the task must be reported as failed'

Source: session=2496623b-5d5a-4f03-a793-83291741378d turn=turn-1

### Subagent dependency chain failure pattern

In code_change workflows, failures in foundational subagents (memory-scout, repo-researcher, api-scout) cause dependent agents (implementation-planner, code-worker) to skip execution, resulting in a total lack of patch artifacts.

Evidence: Log output showing memory-scout/repo-researcher/api-scout failed with child_runtime_error, leading to implementation-planner/code-worker being skipped due to dependency_failed.


Subagents may incorrectly assume workspace constraints (e.g., read-only) or tool requirements (e.g., strict need for orchestrate_agents) based on prior context, even when their own capability profile allows direct actions like write_file.

Evidence: The code-worker subagent assumed the workspace was read-only and that orchestrate_agents was strictly required, despite having write_file capabilities available in its profile.

Source: session=56171e59-aec0-40fe-936f-b1c3298489f2 turn=turn-2
<!-- pp-echo-detail-memory:end -->
