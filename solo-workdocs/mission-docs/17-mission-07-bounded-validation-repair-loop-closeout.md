# Mission 07: Bounded Validation and Repair Loop Closeout

Status: Completed / ready for final human review

## Mission

Mission 07 turns the existing non-executing `ValidationPlan` into a bounded validation and repair loop:

`ValidationPlan -> stage_test_command -> approval -> run_shell -> ValidationObservation -> one repair continuation -> same-command re-validation -> ValidationOutcome`

First version supports pytest only.

## Completed Scope

- 07A: architecture inventory and scope decision.
- 07B: deterministic pytest command selection, bounded `ValidationObservation`, and explicit `ValidationOutcome`.
- 07C: approval-gated validation execution through existing `stage_test_command -> run_shell`.
- 07D-P: trusted structured pytest provenance attestation.
- 07D-R: one bounded repair continuation and one same-command re-validation.
- 07E: existing CLI result exposure, explainability helpers, release regression gate, and closeout docs.

## Key Commits

- `44a3259` docs: define Mission 07 bounded validation repair loop
- `a39eb27` feat: add bounded validation outcome contract
- `8a29f0e` feat: integrate approval-gated validation execution
- `586d4d0` feat: add structured pytest validation provenance
- `a1bcf6e` feat: add one bounded validation repair cycle
- 07E change set: `feat: expose and close out bounded validation repair`

## Architecture Decisions

- Validation recommendation remains owned by `ValidationPlan`.
- Validation execution remains approval-gated and uses existing `stage_test_command`, `approve_pending_action`, and `run_shell`.
- Pytest completion classification is based on trusted plugin attestation, not stdout/stderr or raw exit-code-only inference.
- Repair policy belongs to coding-owned Mission 07 seams, not generic shell tools, approval storage, provider runtime, or `ContextPipeline`.
- CLI exposure reuses the existing `pp-echo code` result serializer and formatter.
- No new trace schema was added; existing runtime, approval, tool trace, and typed outcome contracts provide auditability.
- Doctor remains non-executing and does not run validation, create approvals, invoke a model, or write provenance artifacts.

## Provenance Design

The pytest provenance plugin writes one small attestation artifact per validation execution. Host verification checks:

- schema version;
- trusted plugin identity and version;
- nonce exact match;
- immutable logical command digest;
- category and pytest exit-status consistency;
- timeout/tool failure precedence;
- malformed, missing, stale, mismatched, or oversized artifact fail-closed behavior.

The attestation is consumed and cleaned up after verification. CLI output never exposes nonce, artifact path, raw attestation JSON, plugin internal arguments, or full logs.

## Approval Lifecycle

- Initial validation creates a new staged `run_shell` action.
- Re-validation creates a separate staged action with a fresh nonce, fresh artifact, and fresh approval lifecycle.
- Existing approval tokens are not reused for re-validation.
- Approval pending is represented as pending, not as test failure.
- Approval denied, timeout, tool failure, provenance invalid, pytest internal error, usage error, interrupted, or no tests collected do not trigger repair.

## Bounded Repair Invariants

- `REPAIR TRIGGER: VALIDATED TRUSTED TESTS_FAILED ATTESTATION ONLY`
- `REPAIR ATTEMPTS: MAXIMUM ONE`
- `RE-VALIDATION ATTEMPTS: MAXIMUM ONE`
- `VALIDATION EXECUTIONS: MAXIMUM TWO`
- `COMMAND SELECTION: EXACTLY ONCE`
- `SAME LOGICAL COMMAND: REQUIRED`
- `NO STDOUT/STDERR SEMANTIC PARSING`
- `NO EXIT-CODE-ONLY PROOF`

## CLI Exposure

The existing `pp-echo code` owner is reused.

Machine-readable output can include:

- final validation status;
- safe normalized validation command summary;
- validation execution status;
- pytest completion category;
- repair eligibility;
- repair attempted;
- re-validation attempted;
- bounded failure summary;
- stdout/stderr truncation flags;
- final explanation derived from typed contracts.

Human-readable output distinguishes:

- validation not run;
- validation awaiting approval;
- validation blocked;
- validation passed;
- trusted test failure eligible for repair;
- repair pending or blocked;
- same-command re-validation pending;
- repaired and passed;
- repair attempted but tests still failed;
- re-validation blocked.

## Security and Redaction

CLI, docs, and tests preserve these boundaries:

- no nonce;
- no artifact path;
- no approval token in validation outcome summaries;
- no raw attestation;
- no plugin internal arguments;
- no full temporary paths;
- no environment variables;
- no unbounded stdout/stderr;
- no raw process object;
- no hidden model/tool transcript.

## Release Gate Evidence

Focused tests added or updated:

- `tests/cli/test_validation_cli_outcome.py`
- `tests/coding/test_mission_07_release_gate.py`
- Existing 07B-07D focused tests remain part of the release gate:
  - `tests/coding/test_validation_outcome.py`
  - `tests/coding/test_validation_execution.py`
  - `tests/coding/test_pytest_provenance.py`
  - `tests/coding/test_validation_repair.py`
  - `tests/coding/test_runtime_loop.py`

Required final gate before merge:

- focused Mission 07 tests pass;
- `tests/coding` pass;
- `tests/cli` pass;
- `tests/tools` pass if tool code changes;
- `tests/runtime` pass if runtime code changes;
- full `tests` suite pass;
- `python -m pp_agent.cli.main workflow doctor --json` reports `status: ok`;
- CLI smoke for `code --prepare-only --json` succeeds without model execution;
- `git diff --check` passes;
- worktree is clean after commit.

## Non-goals

Mission 07 does not implement:

- non-pytest validators;
- npm, pnpm, yarn, cargo, go test, CI, GitHub Actions, or remote runners;
- multiple repair attempts;
- multiple validation cycles;
- automatic rollback;
- persistence or cross-process lifecycle resume;
- background workers or scheduled validation;
- second shell executor;
- second approval system;
- second coding runtime;
- generic planner, task DAG, scheduler, or workflow engine;
- Web UI;
- new trace schema;
- full pytest parser or JUnit XML framework.

## Remaining Limitations

- Mission 07 first version is run-local.
- CLI exposes typed outcome summaries but does not itself drive the full validation/repair lifecycle.
- Web-specific presentation is deferred.
- Non-pytest validation support requires a separate mission and separate trusted provenance design.
- Rollback-on-final-validation-failure remains a future decision.

## Future Work

- Mission 07 final human merge review.
- Optional future mission for richer CLI flow around validation approval lifecycle.
- Optional future mission for Web display of typed validation outcome.
- Optional future mission for non-pytest validation families with explicit trusted provenance.
- Optional future mission for rollback policy after failed re-validation.
