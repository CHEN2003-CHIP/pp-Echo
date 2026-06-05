# Release Readiness

The dynamic tool declaration migration is complete. Release checks now use the runtime doctor and the normal test suite; there is no separate migration gate.

Recommended checks:

```powershell
python -m pp_agent.cli.main doctor --workspace .
pytest -q tests/architecture
pytest -q
```

Dynamic tools must use the formal declaration fields (`exact_effect_mode`, `non_side_effectful`, `known_safe_inspect`, `requests_network_hint`, and `touches_external_hint`). Runtime-only risk tightening is handled internally by `risk_overrides`.
