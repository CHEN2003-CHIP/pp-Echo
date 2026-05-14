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
<!-- pp-echo-detail-memory:end -->
