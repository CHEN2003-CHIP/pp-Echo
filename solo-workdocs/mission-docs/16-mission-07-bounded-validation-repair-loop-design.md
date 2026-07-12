# Mission 07: Bounded Validation and Repair Loop Design

Status: Implemented / closeout ready

Scope type: DESIGN RECORD AND IMPLEMENTATION BOUNDARY

This document formally defines Mission 07. It records the completed 07A discovery result, the human-approved validation and repair semantics, the 07B/07C/07D/07E boundaries, and the final implementation constraints. The closeout evidence lives in `solo-workdocs/mission-docs/17-mission-07-bounded-validation-repair-loop-closeout.md`.

## 07A Discovery Record

07A - Post-Mission-06 Architecture Inventory and Next-Mission Discovery

Status: COMPLETED

Discovery conclusion:

The largest current product gap is not repository context, tool execution, or a generic planner.

The largest gap is the missing bounded loop between:

`ValidationPlan -> approval-gated validation execution -> bounded validation observation -> one repair-or-stop decision -> bounded re-validation -> explicit completion outcome`

Decision:

`NO PRE-MISSION HARDENING REQUIRED`

Known technical debt and hardening items do not block Mission 07.

## Official Mission Definition

Official name:

Mission 07 - Bounded Validation and Repair Loop

Category:

`NEXT PRODUCT CAPABILITY`

One-line goal:

Turn the existing non-executing `ValidationPlan` into a bounded, approval-gated validation feedback loop that can observe one pytest validation result, allow at most one repair continuation after a real test failure, re-run the same validation once, and finish with an explicit validated, failed, blocked, or approval-pending outcome.

Mission 07 is not:

- generic self-healing agent
- autonomous infinite repair
- generic planner
- generic test framework

## Capability Lineage

Mission 02:

- safe edits
- checkpoint
- rollback

Mission 03:

- approval-gated shell execution
- `stage_test_command`
- bounded shell result

Mission 04-06:

- repository understanding
- project context
- scoped instructions

Mission 07:

- bounded validation observation
- one repair continuation
- re-validation
- explicit completion outcome

Mission 07 must reuse existing mechanisms. It must not create:

- second shell executor
- second approval system
- second coding runtime
- generic planner framework
- generic workflow engine

## Human Decisions Recorded

Mission name:

- Mission 07 - Bounded Validation and Repair Loop

First-version validation surface:

- pytest validation only
- input originates from existing `ValidationPlan`
- execution is staged through existing `stage_test_command`
- approval uses the existing approval lifecycle
- command execution uses existing `run_shell`
- result handling reuses existing bounded shell result

First-version does not support:

- npm test
- pnpm
- yarn
- cargo test
- go test
- CI jobs
- GitHub Actions
- remote runners
- arbitrary user shell validation
- model-invented validation commands outside `ValidationPlan`

Approval boundary:

- Validation execution must remain approval-gated.
- Prompt text is not a security boundary.
- Do not auto-approve.
- Do not bypass approval digest.
- Do not directly spawn subprocesses.
- Do not call pytest through a second executor.
- Do not execute hidden validation commands.

Approval pending semantics:

- If validation execution is waiting for approval, the outcome is `approval_pending` or the equivalent project-native status.
- `approval_pending` is not `validation_failed`.
- `approval_pending` must not trigger repair.
- Do not create a second approval persistence mechanism.

Execution failure semantics:

- A test failure means the validation command actually executed and returned a test-failing result.
- Execution or infrastructure failure includes policy denial, approval denial, command start failure, shell execution error, timeout, invalid command contract, missing executable, or outside-policy execution.
- Execution or infrastructure failure becomes `blocked` or an equivalent explicit non-repair outcome.
- Do not automatically repair source code because validation infrastructure failed.

Bounded repair policy:

- `MAX_REPAIR_CONTINUATIONS = 1`
- Initial validation pass finishes as `validated`.
- Initial genuine pytest failure allows one repair continuation.
- After repair, exactly one same-command re-validation attempt is allowed.
- Re-validation pass finishes as `validated_after_repair`.
- Re-validation fail finishes as `validation_failed` or blocked completion.
- No second repair continuation.
- No recursive repair.
- No "try until green".
- No model-selected retry count.

Re-validation command:

- Re-validation uses the same normalized validation command as the initial validation cycle.
- The previous approval must not be assumed to authorize re-execution unless the existing approval system explicitly does so.

Trace decision:

- Validation outcome must be auditable.
- First preference is to reuse existing trace / tool execution events.
- Mission 07 should expose enough safe structured information to answer what command was selected, whether approval was pending, whether validation executed, whether it passed/failed/blocked, whether repair was attempted, whether re-validation occurred, and the final validation outcome.
- Do not automatically create a new trace event type.
- If existing trace cannot express the lifecycle, stop: trace schema change requires human review.

CLI decision:

- First version must expose a minimal validation outcome in existing controlled-loop CLI/report output.
- At minimum: validation status, repair attempted, re-validation attempted, and final outcome.
- Do not dump full test logs by default.
- Do not redesign CLI.

Web scope:

- Web-specific new UI is deferred.
- Shared serialization exposure is acceptable if it falls out of existing result surfaces.
- Mission 07 must not become a Web redesign mission.

Persistence and rollback:

- Mission 07 state is first-version run-local.
- Do not add database persistence, checkpointed validation lifecycle, cross-process resume, background workers, or scheduled validation.
- Mission 07 first version does not automatically rollback after failed validation.
- Rollback-on-final-validation-failure is a future extension requiring separate human decision.

## ValidationPlan Pre-implementation Audit Requirement

Before 07B implementation, perform a required pre-implementation audit of the real contracts:

- `ValidationPlan`
- `ValidationCommand`
- `stage_test_command`

Determine:

1. whether `ValidationPlan` can contain multiple commands;
2. whether command order is deterministic;
3. whether commands are already typed/classified as pytest;
4. whether commands are already bounded;
5. whether one command can be selected without model guesswork.

Do not invent command-selection semantics before this audit.

First-version target:

- one primary eligible pytest validation command per validation cycle

If the current `ValidationPlan` already has a stronger deterministic concept such as primary or ordered commands, reuse it.

If no safe deterministic primary command can be selected:

`STOP - VALIDATION COMMAND SELECTION REQUIRES HUMAN REVIEW`

Do not silently choose a random command.

## Validation Observation Contract

Mission 07 may introduce one minimal domain record, conceptually:

`ValidationObservation`

Purpose:

Normalize an actually executed validation result into bounded structured evidence.

Candidate fields may include:

- validation command identity
- execution status
- exit code
- bounded stdout/stderr or existing bounded result reference
- truncated flags
- failure summary

Exact fields belong to 07B contract design.

Do not introduce:

- `ValidationFramework`
- `TestResultRegistry`
- generic observation bus
- universal command result framework

First version should not build a complete pytest parser. Minimum stable evidence is command identity, executed/not executed, exit code, bounded output, truncation, and high-level validation status.

## Validation Outcome Contract

Mission 07 may introduce one minimal final outcome contract, conceptually:

`ValidationOutcome`

It should express at least:

- `not_run`
- `approval_pending`
- `passed`
- `failed`
- `blocked`

It should also carry repair metadata such as:

- `repair_attempted`
- `revalidation_attempted`

Exact enum and field design belong to 07B. Do not create a large generic workflow-state machine.

Mission 07 first version must produce an explicit controlled-loop completion outcome. Conceptually distinguish:

- `validated`
- `validated_after_repair`
- `validation_failed`
- `blocked`
- `approval_pending`
- `not_validated`

Max iteration exhaustion must not be the only way to understand task completion.

Mission 07 owns only validation-aware completion, not a generic task DAG, subtask graph, planner lifecycle, or project management state machine.

## Controlled Loop Ownership

The validation/repair lifecycle belongs to:

- controlled coding workflow
- controlled coding loop

It does not belong to:

- generic `ContextPipeline`
- `ToolRegistry`
- shell tool
- provider layer
- Web UI

The generic shell executor must remain unaware of repair policy, validation lifecycle, and coding completion semantics.

`ValidationPlan` remains the source of recommended validation. Mission 07 upgrades it from non-executing recommendation into bounded execution input through a separate execution/observation seam.

Do not mutate `ValidationPlan` into runtime state, repair state, or approval state. Keep recommendation and runtime outcome responsibilities separate.

Repair continuation must reuse:

- existing controlled coding loop
- existing `ContextPipeline`
- existing repository context
- existing scoped instructions
- existing tool approval / policy / guardrails

Do not create:

- `RepairAgent`
- `RepairRuntime`
- `SelfHealingLoop`
- `SecondaryAgent`

## Repair Context Boundary

A repair continuation may receive a bounded `ValidationObservation` through an existing context/runtime seam.

The model must not receive:

- unbounded stdout
- unbounded stderr
- full shell transcript
- full pytest log beyond existing limits
- raw process object

Do not inject raw pytest output directly into the system prompt. Do not create a second `ContextPipeline`. Do not append hidden provider messages. Do not bypass existing context budgets.

Exact integration belongs to 07D after auditing existing context seams.

## 07B Boundary

07B - Validation Observation and Outcome Contracts

Single goal:

`existing validation execution result -> bounded structured ValidationObservation -> explicit ValidationOutcome contract`

Includes:

- audit `ValidationPlan` / `ValidationCommand`
- pytest eligibility
- deterministic primary command selection
- observation contract
- outcome contract
- test-failure vs execution-failure classification
- bounded result normalization
- focused tests

Does not include:

- controlled loop execution
- repair continuation
- `ContextPipeline` integration
- CLI integration

Recommended commit:

`feat: add bounded validation outcome contract`

## 07C Boundary

07C - Approval-gated Validation Execution Integration

Single goal:

`ValidationPlan -> stage_test_command -> approval lifecycle -> run_shell -> ValidationObservation`

Includes:

- controlled-loop validation execution seam
- `approval_pending` outcome
- actually executed validation observation
- no repair yet
- tests for pass/fail/blocked/pending

Does not include:

- repair continuation
- re-validation
- generic planner

Recommended commit:

`feat: execute bounded validation plans`

## 07D Boundary

07D - One Repair and Re-validation Policy

Single goal:

`real pytest failure -> one repair continuation -> same-command re-validation -> final validation-aware completion`

Includes:

- one repair continuation
- bounded failure observation into repair context
- same validation command reused
- one re-validation attempt
- stop after second result
- no recursion

Recommended commit:

`feat: add one-shot validation repair loop`

## 07E Boundary

07E - CLI / Trace / Closeout / Release Gate

Single goal:

`validation-aware outcome -> existing result/report surface -> auditability -> Mission 07 closeout`

Includes:

- minimal CLI outcome
- trace audit
- no new trace schema unless separately approved
- regression
- full suite
- doctor
- closeout docs

Recommended implementation/docs commits as appropriate.

Implementation result:

- Existing `pp-echo code` CLI ownership is reused.
- CLI JSON and human-readable output expose typed `ValidationOutcome` and `ValidationRepairCycleState` summaries.
- CLI output is presentation-only and does not trigger validation, approval, repair, or re-validation.
- No new trace schema was added; Mission 07 remains auditable through existing runtime/tool/approval traces plus typed validation result contracts.
- Doctor remains non-executing and was not extended to run validation or repair.

## Explicit First-version Scope

Mission 07 includes:

- `ValidationPlan` audit
- pytest-only validation eligibility
- one deterministic primary validation command per cycle
- existing `stage_test_command` path
- existing approval flow
- existing `run_shell` path
- bounded validation observation
- test-failure vs execution-failure distinction
- one repair continuation
- same-command re-validation
- explicit validation-aware completion outcome
- existing controlled-loop integration
- minimal CLI outcome display
- trace auditability through existing mechanisms
- release gate

## Final Implementation Invariants

Mission 07 runtime semantics are fixed at:

- `REPAIR TRIGGER: VALIDATED TRUSTED TESTS_FAILED ATTESTATION ONLY`
- `REPAIR ATTEMPTS: MAXIMUM ONE`
- `RE-VALIDATION ATTEMPTS: MAXIMUM ONE`
- `VALIDATION EXECUTIONS: MAXIMUM TWO`
- `COMMAND SELECTION: EXACTLY ONCE`
- `SAME LOGICAL COMMAND: REQUIRED`
- `CLI OUTPUT SOURCE: TYPED VALIDATION OUTCOME`
- `NO STDOUT/STDERR SEMANTIC PARSING`
- `NO SENSITIVE PROVENANCE DATA EXPOSED`

The pytest provenance plugin and verifier are coding-owned. Generic shell tools and approval storage do not classify pytest completion category or own repair policy.

## Explicit Deferred Scope

Deferred:

- multiple repair attempts
- multiple validation cycles
- multi-command validation suite orchestration
- npm / pnpm / yarn
- cargo / go test
- CI execution
- remote validation
- background validation
- persistent resume
- automatic rollback
- generic planner
- task DAG
- Web redesign
- full pytest parser
- JUnit XML framework

Rejected for first version:

- approval bypass
- direct subprocess execution
- arbitrary model-generated validation commands
- infinite self-repair
- raw unbounded test-log prompt injection
- second shell executor
- second `ContextPipeline`
- second provider-message path

## Do-Not-Reinvent Record

| Requirement | Decision |
| --- | --- |
| validation recommendation | REUSE `ValidationPlan` |
| test staging | REUSE `stage_test_command` |
| command execution | REUSE `run_shell` |
| approval | REUSE existing approval flow |
| bounded output | REUSE existing shell result |
| coding continuation | REUSE controlled coding loop |
| context | REUSE `ContextPipeline` |
| repository context | REUSE Mission 04-06 |
| validation observation | NEW MINIMAL MISSION 07 SEAM |
| validation-aware outcome | NEW MINIMAL MISSION 07 SEAM |
| one-repair policy | NEW MINIMAL MISSION 07 SEAM |
| generic planner | REJECT / DEFER |
| new executor | REJECT |

## Threat and Edge-case Requirements

Future implementation must test at least:

- `ValidationPlan` missing
- `ValidationPlan` empty
- no eligible pytest command
- multiple commands but deterministic primary selection
- approval pending
- approval denied
- policy denied
- pytest pass
- pytest fail
- shell execution error
- timeout
- bounded/truncated output
- repair not attempted on infrastructure failure
- repair attempted exactly once on genuine test failure
- same validation command used for re-validation
- re-validation pass
- re-validation fail
- no second repair
- non-coding runtime unchanged
- approval semantics unchanged
