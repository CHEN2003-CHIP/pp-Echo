# Shared Effect Analysis

This document captures the current cross-tool effect analysis layer that generalizes safety semantics across built-in file tools, shell tools, and dynamic extension or MCP tools.

## Shared Effect Analysis Phase 2C

Phase 2C generalizes effect semantics across built-in file tools, shell tools, and dynamic extension or MCP tools.

- Shared analysis records expose `family`, `risk_class`, `summary`, `confidence_band`, `touches_workspace`, `touches_external`, `requests_network`, `destructive_hint`, and `protected_path_hint`.
- Policy uses stable confidence bands such as `high`, `medium`, `low`, and `unknown` instead of relying on raw float thresholds.
- Built-in file reads can still be allowed automatically when the target is a normal workspace path and analysis is high confidence.
- Shell policy differentiation stays intentionally narrow: only a known-safe inspect subset such as `git status`, `git diff`, `rg`, `grep`, `ls`, `dir`, and `Get-ChildItem` may be eligible for automatic allow.
- Extension and MCP tools receive shared analysis too, but that does not mean they have shared exact-effect approvals. Without staged exact-effect support, they remain policy-level `ask` or `deny`.

## Current limits

- Shared analysis is still heuristic and conservative.
- Unknown or weakly understood extension or MCP semantics fail closed.
- Only security-relevant, stably recomputable analysis fields are included in effect identity.
- Shared analysis improves policy and review semantics, but it does not by itself add sandboxing or physical control-plane separation.

## How this fits with dynamic tool declarations

Shared effect analysis now works together with explicit dynamic tool declarations:

- declarations provide the author-facing intent,
- shared analysis tightens risky fields conservatively at runtime,
- unstable or unstageable calls still fail closed.

For declaration details, examples, and migration guidance, see [dynamic-tool-declarations.md](dynamic-tool-declarations.md).
