# Dynamic Tool Declarations

## 1. 这个文档解决什么问题

Dynamic tool declarations describe which tools pp-Echo can expose to a model, what arguments those tools accept, and what safety metadata surrounds them.

They are part of pp-Echo's teaching-oriented Agent Runtime architecture: tool declarations make the model/tool boundary visible, auditable, and testable. A declaration is not permission to do anything dangerous. It is only the structured description that lets the runtime decide whether a tool can be shown, called, approved, traced, or rejected.

## 2. Tool Declaration 和 Tool Execution 的区别

A tool declaration is metadata:

- tool name
- natural-language description
- JSON schema parameters
- permission domain
- confirmation requirement
- tool family and category
- exact-effect declaration for approval staging

Tool execution is the actual runtime action. Execution goes through `ToolRegistry.execute()`, policy evaluation, guardrails, approval staging when needed, cancellation checks, and TraceInspect recording.

This separation matters because read-only APIs such as `metadata()` and `openapi_specs()` should be cheap and side-effect free. They must not instantiate tool classes or touch external resources just to describe available tools.

## 3. ToolRegistry 的职责

`ToolRegistry` is pp-Echo's central tool surface. It owns the registry of built-in tools, dynamically registered extension/MCP tools, model-callable schemas, policy evaluation, exact-effect staging, host-approved execution, and middleware tracing.

The registry does not run the Agent loop. `AgentRuntime` decides when the model asks for a tool; `ToolRegistry` decides whether that tool exists, whether it is allowed, whether it needs approval, how it executes, and what trace summary is emitted.

## 4. Built-in Tools

Built-in tools are registered by the runtime itself. Examples include file tools, repository inspection tools, shell staging, approval tools, safe rewind tools, and attachment tools.

Built-ins have stable names and schemas. Some are model-callable, while host-only tools such as approval preview/execution are hidden from model tool schemas.

## 5. Attachment Tools

Attachment tools expose session-scoped uploaded files without copying them into the workspace or injecting full file bodies into the prompt.

The current attachment tools are:

- `list_attachments`
- `inspect_attachment`
- `search_attachment`
- `read_attachment_chunk`
- `read_attachment_range`
- `search_attachment_symbols`
- `read_attachment_symbol`

These tools are registered with `ToolRegistry`, but read-only registry APIs do not eagerly instantiate them. The model sees their schemas and can call them when it needs attachment content. Actual reads remain explicit, traceable, and bounded.

Workspace import and memory ingest are not ordinary read declarations. Import creates an Approval Gate pending action before any workspace write. Memory ingest is explicit and capped because it persists attachment-derived knowledge beyond the current session.

## 6. MCP, Browser, SKILL, and SubAgent Tools

MCP and Browser tools are dynamic or extension-backed capabilities. SKILL integrations may inject context, commands, or tools depending on policy. SubAgent tools are special coordination tools and are guarded by explicit user intent and capability profiles.

These tools differ from built-ins because their availability may depend on configuration, installed extensions, connected servers, or selected subagent profiles. They still flow through the same declaration, policy, approval, and trace contracts.

## 7. Lazy Materialization

Lazy materialization means `ToolRegistry` can list metadata and produce OpenAI-compatible tool schemas without creating concrete tool instances.

This prevents accidental side effects during capability discovery, startup, tests, or UI inventory calls. Tool instances should be created only when execution actually needs them, then cached when safe.

Attachment tools follow this rule: registering `list_attachments` or `search_attachment` does not scan attachment folders or open files until the tool is executed.

## 8. Tool Schema 如何进入模型上下文

Model-callable tools are converted to OpenAI-compatible function schemas by `ToolRegistry.openapi_specs()`. The runtime sends those schemas with provider requests so the model can choose a tool call.

Schemas should be precise enough for the model to call correctly, but they should not include secrets, file contents, raw approval payloads, or implementation-specific local absolute paths.

## 9. ToolRegistry Middleware Trace

`ToolRegistry.execute()` wraps model-callable execution in a `tool.call` span when observability is active. The span records:

- tool name and call id
- tool family/category
- permission domain
- schema keys
- sanitized arguments
- bounded output preview
- redacted details
- error summary when execution fails

Attachment tool trace output is additionally bounded so `read_attachment_chunk`, `read_attachment_range`, and `read_attachment_symbol` do not write full chunk text into TraceInspect. Search traces record mode, fallback reason, result counts, source refs, and snippets.

## 10. 安全与审批

A declaration does not bypass Approval Gate. Write operations, shell execution, workspace import flows, memory ingest, or other persistent actions must still pass policy and confirmation.

High-risk actions should produce exact effects where possible: stable target path, normalized arguments, digest, risk analysis, and preview. The host can then approve or reject a concrete action instead of a vague intention.

The declaration field `exact_effect_mode` controls whether a dynamic tool can produce an exact, digest-bound effect for Approval Gate. `required` means the tool must stage a concrete effect before execution, `auto` allows direct execution only for narrow high-confidence inspect calls, and `none` means the tool cannot be safely represented for host approval.

## 11. 常见问题

**Does exposing a tool mean the model can execute it freely?**

No. The declaration lets the model request the tool. Runtime policy and approval decide whether it actually runs.

**Why not materialize tools during `metadata()`?**

Discovery should be cheap and safe. Materializing tools during metadata reads can accidentally touch files, start external clients, or make startup slow.

**Why are attachment tools read tools?**

Uploaded attachments are session-scoped read sources. They should be inspected and searched by tools instead of pasted into prompts. Importing an attachment into the workspace is a separate write action and must go through Approval Gate.

**How does this relate to TraceInspect?**

Tool declarations describe the possible action. Tool middleware trace records the actual requested action, policy metadata, sanitized inputs, bounded outputs, and errors so a run can be audited later.
