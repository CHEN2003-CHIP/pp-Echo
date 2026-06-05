# Dynamic Tool Declarations

Dynamic extension and MCP tools describe safety behavior with formal declaration fields only:

- `exact_effect_mode`: `none`, `auto`, or `required`
- `non_side_effectful`: marks a tool as read-only when true
- `known_safe_inspect`: allows high-confidence inspect behavior when paired with `non_side_effectful=True`
- `requests_network_hint`: declares network access
- `touches_external_hint`: declares effects outside the workspace

Runtime adapters may add private `risk_overrides` when host-side discovery proves that a tool is more risky than its static declaration. These overrides only tighten policy decisions and are not part of the public extension API.

Use the runtime doctor and architecture tests for release checks:

```powershell
python -m pp_agent.cli.main doctor --workspace .
pytest -q tests/architecture
```
