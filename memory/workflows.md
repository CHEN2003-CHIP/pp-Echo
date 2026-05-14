# Workflows

<!-- pp-echo-detail-memory:begin -->
### Subagent Memory Context Inheritance Pattern

Implement a mechanism where `spawn_subagent` accepts an `inherit_memory_context=True` parameter. When enabled, the parent agent's high-confidence `memory_search` results are automatically injected as System Prompt into the child agent to prevent context loss and redundant retrieval.

Evidence: Findings indicate current subagent launches create new sessions without inheriting memory state, causing repeated token consumption and potential decision inconsistency in long conversations.

Source: session=538ca3f9-726d-4906-95fd-15596a7f6e50 turn=turn-2

### Subagent Orchestration Safety Protocol

To prevent stack overflow and resource leaks, the orchestration logic must enforce a maximum recursion depth check at the spawn_subagent entry point and ensure explicit disposal of subagent session handles upon termination.

Evidence: Findings B: 'Recursive depth' risk (no max nesting limit); 'Resource leak' risk (missing Dispose calls).

Source: session=1108985f-6d4d-437a-8e3a-de37060bc4d4 turn=turn-2

### Tool Registry Security and Permission Grading

Implement a risk-level classification system within the ToolRegistry. Tools should be tagged with 'risk_level' (low/medium/high). High-risk tools (e.g., destructive file operations, git pushes) must trigger a mandatory secondary confirmation or human approval step before execution to prevent accidental data loss or unauthorized changes.

Evidence: Observation that current 'ToolRegistry' lacks fine-grained sandbox control or permission isolation, posing risks for dangerous commands like 'rm -rf'.

Source: session=1a9402c0-42f7-474d-808d-b38cda46f936 turn=turn-2

### Subagent Orchestration and Memory Retrieval

The SubagentManager class orchestrates child agents with session-scoped tool routing and timeout handling. Memory retrieval is restricted to MEMORY.md and memory/**/*.md files using a hybrid BM25/vector search approach.

Evidence: src/pp_agent/subagents/subagent_manager.py contains the SubagentManager class logic; src/pp_agent/memory/search.py implements the retrieval mechanism.

Source: session=f94b4bee-ef7b-4a44-bdb8-fef009609ae4 turn=turn-2

### Parallel Analysis Strategy for Multi-Module Projects

For analyzing complex projects like pp-Echo, assign specific sub-modules to dedicated agents (e.g., README.md to memory-scout, AGENTS.md to repo-researcher). If an agent fails due to turn limits, consider increasing the limit or splitting the scope further rather than retrying the exact same prompt.

Evidence: The workflow successfully assigned three distinct modules to three agents; one succeeded while two failed due to turn limits, suggesting the need for parameter adjustment or task decomposition.

Source: session=941f6f6c-e8d9-4bc1-a043-73379a04c142 turn=turn-2

### ToolRegistry Security Gaps

The ToolRegistry currently lacks runtime permission checks and sandboxing. File operations can access arbitrary paths, and global state changes can cause side effects during concurrent execution of subagents.

Evidence: Subagent Implementation section in findings; Recommended next action.

Source: session=9abfdf73-d284-4650-b690-b55d85d7b17d turn=turn-1

### Subagent Orchestration and Validation

SubagentManager orchestrates parallel execution via orchestrate_agents. It validates outputs by stripping formatting artifacts and triggers an invalid_summary state if the output exceeds 2500 characters or lacks required sections.

Evidence: src/pp_agent/subagents implementation details regarding orchestrate_agents, output parsing logic, and validation thresholds.

Source: session=abcaba04-9664-4de8-b302-91d488c70e92 turn=turn-1

### Parallel Subagent Orchestration Protocol

The project utilizes a parallel subagent orchestration system to analyze core modules simultaneously with read-only access by default to ensure safety during architectural mapping.

Evidence: Evidence from previous turns confirms 'orchestrate_agents' ran 3 subagents in parallel for read-only analysis of specific modules like README.md and AGENTS.md.

Source: session=6306c941-e74e-42a8-aad6-06693f8429a2 turn=turn-3
<!-- pp-echo-detail-memory:end -->
