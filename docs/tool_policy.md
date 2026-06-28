# Tool Policy

All tool execution must pass through `ToolRegistry` policy checks before a tool
body runs. The policy decision is traceable as `policy.decision`, and execution
is traceable as `tool.call`.

Contract rules:

- Every tool execution attempt creates or receives a policy decision first.
- Read-only mode blocks write, shell, and unsafe execution.
- Approval-required tools stage an approval instead of mutating immediately.
- Approval grants are scoped by session, run/effect, and tool call metadata.
- Approval grants are single-use by default and cannot be reused across unrelated
  sessions or payload digests.
- Blocked attempts, tool errors, and approval resumes are traceable.
- Runtime, bot, and approval paths must not execute tools outside `ToolRegistry`.

The policy stance is inspired by Hermes Agent patterns: dangerous-command
detection, approval callbacks, session-scoped approval state, and allowlist-style
handling for risky tools. pp-Echo keeps this lightweight and local: the policy
helper decides, while `ToolRegistry` remains the execution boundary.

`ToolPolicyDecision` is the stable schema for policy-relevant metadata. It
exposes tool identity, run/session scope, read-only state, approval requirement,
risk level, side-effect type, allowed/blocked outcome, budget cost, and approval
scope without replacing the existing evaluator.
