# Release Readiness

This page summarizes the current release-readiness checks that matter most for user-facing capability declarations and runtime health.

## Legacy Hint Doctor

The legacy-hints doctor now doubles as a release gate for the dynamic tool declaration cutover.

- Use `pp-agent capabilities legacy-hints --workspace <path>` for a human-readable report.
- Use `pp-agent capabilities legacy-hints --json --workspace <path>` for machine-readable output.
- Use `pp-agent capabilities legacy-hints --strict --workspace <path>` to fail the command when author-facing legacy usage remains.
- Runtime metadata is the authoritative readiness source.
- Static source scanning is advisory only and does not decide readiness by itself.
- Author-facing legacy `analysis_hints` count as removal blockers.
- Runtime-internal risk overrides are reported separately.
- Removal readiness for `v0.4.0` requires zero author-facing legacy `analysis_hints` in runtime metadata.

## Why this matters

The project now treats explicit dynamic tool declarations as the public semantics contract. That means release readiness is not only about tests passing; it also means:

- public extension and MCP registrations use the formal declaration fields,
- old author-facing hints are gone from runtime metadata,
- weak or unstable semantics fail closed rather than slipping through ambiguous defaults.

For the declaration model itself, see [dynamic-tool-declarations.md](dynamic-tool-declarations.md).

## Recommended checks before a release

```powershell
python -m pp_agent.cli.main capabilities legacy-hints --strict --workspace .
python -m pp_agent.cli.main workflow doctor --json --workspace .
python -m pytest tests/benchmarks/test_runner.py
```

## Scope note

Current readiness checks help with:

- declaration migration correctness,
- runtime health visibility,
- benchmark-backed regression detection.

They do not imply:

- a full shell sandbox,
- a historical grant ledger,
- or physical control-plane separation.
