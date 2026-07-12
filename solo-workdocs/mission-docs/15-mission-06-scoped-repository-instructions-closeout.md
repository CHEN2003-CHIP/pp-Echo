# Mission 06 Scoped Repository Instructions Closeout

## Status

Completed / ready for human merge review.

Mission 06 delivers scoped repository instructions through the existing context path:

```text
active ScopedInstruction records
-> ContextItem(section="project_context")
-> existing ContextPipeline
-> ContextPack
-> final_messages
-> existing context_built trace
```

## Completed Scope

- 06A benchmarked OpenCode source-level scoped instruction behavior and ratified pp-Echo semantics.
- 06B added `ScopedInstruction`, bounded ancestor resolution, `AGENTS.md` canonical handling, nested `CLAUDE.md` fallback, root exclusion, symlink safety, bounded reads, deterministic ordering, and bounded decoded canonical content digests.
- 06B follow-up preserved root `CLAUDE.md` fallback compatibility in the Mission 04/05 root instruction path.
- 06C added `ScopedInstructionActivationState`, TaskScope concrete-path seeding, successful `read_file` lazy activation, run-scoped active sets, duplicate claim handling, freshness replacement, and bounded warning retention.
- 06D adapted active scoped instruction records into `ContextItem` values and integrated them through the existing `ContextPipeline`.
- 06D keeps warnings non-model-facing and preserves trace-safe provenance through existing `SourceRef` and `context_built` details.

## Integration Decisions

- Mission 05 remains the owner of repository root instructions and repository summary integration.
- Mission 06 owns nested scoped instruction resolution and activation only.
- Scoped instructions use the existing `project_context` section; no new context section was added.
- Runtime integration is optional: normal `AgentRuntime` instances without the controlled coding loop keep existing behavior.
- The controlled coding loop installs a run-scoped context provider during execution and restores it afterwards.
- The provider reads the current activation state on each context build, so TaskScope seeds can appear in the first model context and read-triggered instructions appear in the next provider context.

## Ordering and Budget Semantics

- Render order preserves the approved hierarchy: root project context first, then shallow scoped instructions, then deeper/nearest scoped instructions.
- Budget selection uses existing whole-item `ContextBudgeter` behavior and existing drop reasons.
- Scoped instruction priority increases with scope depth so nearer instructions are not systematically disadvantaged under tight `project_context` budgets.
- No new budget engine, truncation engine, or renderer was introduced.

## OpenCode Adoption and Divergence

- Adopted: nearby instruction files, ancestor-chain accumulation, deterministic same-directory precedence, and lazy activation based on concrete file access.
- Diverged: pp-Echo does not introduce a second prompt assembly path; scoped instructions are normalized into existing context items and budgeted with the rest of project context.
- Deferred: custom rule names, remote rules, broad recursive scans, edit-triggered activation, and global/session-wide rule registries.

## Verification Summary

- Adapter tests cover source identity, metadata safety, deterministic output, nearest-first budget ordering, warning exclusion, and no filesystem reads.
- Runtime bridge tests cover final messages, trace provenance, existing budget drops, root/scoped ownership, no rereads, and nearest instruction behavior under budget pressure.
- Controlled loop tests cover TaskScope first-context visibility, read-triggered next-context visibility, failed-read non-activation, duplicate suppression, and provider restoration.
- Mission 06B and 06C focused regressions passed.
- Context, coding, and runtime regression suites passed during 06D implementation.

## Deferred Scope

- No edit trigger.
- No global rules.
- No remote rules.
- No custom globs or custom instruction filenames beyond `AGENTS.md` and `CLAUDE.md`.
- No `CONTEXT.md`.
- No generic recursive scan.
- No new `ContextPipeline`.
- No new provider-message path.
- No new trace schema.
- No dependency additions.

## Known Non-blocking Notes

- The resolver still reuses repository-summary collector private helpers. This is acceptable for the MVP but can be revisited if collector ownership is refactored.
- The digest is a bounded decoded canonical content digest, not a full raw-file digest or security hash.
- Direct unreadable/existing-directory/internal-symlink resolver hardening can be expanded later without changing the 06D context integration contract.
- Hook restoration and multiple-run behavior have indirect focused coverage; a future hardening pass may add narrower tests if the hook system changes.
