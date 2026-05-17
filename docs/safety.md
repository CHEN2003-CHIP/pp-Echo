# Safety and Approvals

This document collects the safety material that used to live inline in the README home page. It describes the current implemented boundary, the exact-effect approval model, and the present shell-review semantics.

## Safety Boundary Phase 1

Phase 1 uses a mandatory policy gate for sensitive execution. The gate is enforced at execution time, not only at planner time.

- The policy gate returns `allow`, `ask`, or `deny`.
- `ask` means the model can stage a proposed effect, but only the host or user side may approve it.
- Protected paths are enforced through path protection plus policy gating.
- This phase is not a true shell sandbox. The existing shell runner remains in place behind the policy gate and host approval flow.

Protected paths in Phase 1:

- `.pp-agent/**`
- `.git/**`
- `.env`
- `.env.*`
- `*.pem`
- `*.key`

Important Phase 1 limit:

- `.pp-agent/**` is logically isolated from model-facing tools, but it is not physically separated from the repository yet.

## Exact-Effect Approvals Phase 2A

Phase 2A upgrades sensitive approval binding so host approval applies to an exact staged effect, not just a token.

- Sensitive file and shell proposals produce an effect record before execution.
- `payload_digest` is the primary approval binding.
- Human-readable summaries are review output and a secondary consistency check, not the primary security anchor.
- File effects distinguish whether the target was absent or present at staging time.
- Shell effects use narrow normalization: whitespace-only differences normalize, but command content, separators, redirection, quotes, parameter order, and timeout changes remain material.
- Planner approval is still not execution approval.
- The Web UI mirrors the two-step model: first approve the plan, then approve or apply the concrete staged write, edit, or command.

## Shell Effect Classification Phase 2B

Phase 2B keeps exact-effect approval binding, but makes staged shell effects easier to review and reason about.

- Shell effects now include structured fields such as `normalized_command`, `command_head`, `risk_class`, `writes_workspace_files`, `touches_external_paths`, `requests_network`, and `destructive_hint`.
- Current shell classes are `inspect`, `workspace_mutation`, `external_mutation`, `networked`, and `destructive`.
- Human-readable shell summaries are stable review output such as `Inspect repository status with git status` or `Fetch remote content with curl`.
- Classification enriches policy decisions and previews, but it does not bypass host-side approval and it is not a shell sandbox.
- Normalization remains intentionally narrow: whitespace-only differences normalize to the same effect, while command, parameter, separator, redirection, quote, and timeout changes remain material.

Current Phase 2B limits:

- Shell classification is still conservative heuristic matching, not a full shell parser or AST.
- The existing shell runner is still used; this phase does not add sandbox infrastructure.
- Policy still keeps shell execution behind host-side approval even for `inspect` commands.

## Relationship to later phases

- Shared cross-tool analysis now lives in [effect-analysis.md](effect-analysis.md).
- Dynamic author-facing tool declarations now live in [dynamic-tool-declarations.md](dynamic-tool-declarations.md).
- Release-gate checks for legacy declarations now live in [release-readiness.md](release-readiness.md).

## Quick command references

```powershell
python -m pp_agent.cli.main approvals list
python -m pp_agent.cli.main approvals summary
python -m pp_agent.cli.main workflow doctor --json
```
