# Lessons

<!-- pp-echo-detail-memory:begin -->
### Tool Metadata for Memory Validity

Enhance `ToolRegistry` tool descriptions to include metadata regarding 'memory timeliness'. This prevents agents from misusing expired memory files by explicitly marking the validity or freshness of data sources within tool definitions.

Evidence: Analysis of `src/pp_agent/tools/registry.py` revealed a lack of temporal metadata in tool descriptions, identified as a risk for using stale information.

Source: session=538ca3f9-726d-4906-95fd-15596a7f6e50 turn=turn-2

### Thread Safety Vulnerability in Dynamic Tool Registration

The ToolRegistry allows dynamic tool registration via RegisterTool without locking mechanisms. This creates a race condition in multi-threaded environments and lacks fine-grained sandboxing for subagents.

Evidence: Findings C: 'Concurrency safety' issue identified where RegisterTool is not thread-safe; 'Permission isolation' is missing.

Source: session=1108985f-6d4d-437a-8e3a-de37060bc4d4 turn=turn-2

### Long-term Memory: Missing Active Summarization Hook

The current memory implementation relies on passive retrieval (memory_search/memory_get) triggered by user queries. There is no automated hook in AgentRuntime to summarize and persist key information at the end of a turn, leading to potential loss of critical context in long conversations.

Evidence: Analysis of src/services/memory/MemoryService.ts and src/core/runtime/AgentRuntime.ts indicates 'Passive Retrieval' pattern and 'Active Write missing'.

Source: session=a14bce13-e570-416d-bff3-5af8164eae2f turn=turn-2

### Subagent Orchestration: Recursion and Resource Leak Risks

The spawn_subagent logic lacks a maximum recursion depth check, creating a risk of infinite loops if intent recognition triggers nested subagents recursively. Additionally, exception paths (e.g., timeouts) may fail to properly clean up subagent processes, causing resource leaks.

Evidence: Findings from src/orchestration/OrchestrationService.ts highlight 'Dead Loop' risk due to lack of strict intent logic and 'Resource Leak' in abnormal execution paths.

### Tool Strategy: Lack of Runtime Permission Controls

While ToolRegistry uses JSON Schema for parameter validation, it lacks runtime dynamic confirmation or whitelist mechanisms for sensitive operations (e.g., file deletion, shell execution). Reliance solely on tool descriptions creates a risk of privilege escalation or unintended destructive actions.

Evidence: Inspection of src/tools/ToolRegistry.ts reveals 'Permission Overreach' risk where high-risk tools like file_delete and shell_exec lack interactive confirmation steps.

### Subagent Recursion Risk and Mitigation

Dynamic subagent spawning without a maximum depth limit creates a high risk of infinite recursion and stack overflow. A robust orchestration system must enforce a 'max_depth' parameter (e.g., default 3) at the spawn level and explicitly prohibit self-replication in system prompts to prevent context pollution and resource exhaustion.

Evidence: Analysis of 'spawn_subagent' logic showing dynamic instantiation without depth checks; identification of potential circular dependency where subagents can spawn further agents indefinitely.

Source: session=1a9402c0-42f7-474d-808d-b38cda46f936 turn=turn-2


Dynamic subagent spawning without explicit stack depth limits (max_depth) creates a high risk of infinite recursion loops (e.g., Agent A -> B -> A). The system requires an implementation of a recursion counter in the spawn logic to automatically reject requests exceeding a threshold (e.g., 3 levels).

Evidence: Findings section 1.2: 'Lack of max_depth or call_stack check... Subagent A -> B -> A dead loop'. Recommended action 2: 'Introduce recursion_depth counter'.

Source: session=326b2ecb-9061-41a1-92a7-c162233d1356 turn=turn-2

### Memory Retrieval Robustness and Concurrency

The memory_search tool's 'auto' mode may silently degrade to pure BM25, failing vector retrieval for specific terms. Concurrent writes to memory files by multiple agents lack locking mechanisms, risking data corruption. Path hardcoding restricts cross-directory retrieval. Improvements involve forcing keyword fallback with warnings on low confidence and implementing file locks in MemoryService.

Evidence: Findings section A: 'Retrieval degradation... silent failure'; 'Concurrent conflict... no explicit lock mechanism'. Recommended actions 2.

Source: session=375b0f5e-d8a3-4fea-8888-ec0ec104c9a6 turn=turn-2

### Memory Search Path Limitations

The memory retrieval system uses hybrid BM25/vector search restricted to hardcoded paths (MEMORY.md and memory/**/*.md). This configuration may fail to retrieve information from newly created .md files outside these specific directories.

Evidence: Subagent Implementation section in findings; Memory Module section in findings.

Source: session=9abfdf73-d284-4650-b690-b55d85d7b17d turn=turn-1

### ToolRegistry Security Gap

The current ToolRegistry implementation lacks runtime permission checks and sandboxing, presenting a potential security risk that requires review.

Evidence: Findings section notes 'Tool registry lacks runtime permission checks/sandboxing (security risk noted in memory)' based on inspection of src/pp_agent/subagents.

Source: session=abcaba04-9664-4de8-b302-91d488c70e92 turn=turn-1

### Subagent Output Format Standardization

All subagent responses must strictly follow a 5-section format (Summary, Findings, Recommended next action, Files/paths inspected, Confidence). Markdown headers, numbering, code fences, and raw file dumps are prohibited as they break parsing.

Evidence: Multiple evidence entries confirm strict adherence to the 5-section plain text format is required; violations trigger invalid_summary failures or require normalization.

Source: session=6306c941-e74e-42a8-aad6-06693f8429a2 turn=turn-3
<!-- pp-echo-detail-memory:end -->
t... memory confusion'. Recommended actions 1 and 4.

Source: session=375b0f5e-d8a3-4fea-8888-ec0ec104c9a6 turn=turn-2
<!-- pp-echo-detail-memory:end -->
urn-2
<!-- pp-echo-detail-memory:end -->
