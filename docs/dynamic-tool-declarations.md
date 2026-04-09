## Dynamic Tool Declarations

Dynamic extension and MCP tools now use explicit registration declarations as the primary semantics contract.

Primary declarations:

- `exact_effect_mode`: `none`, `auto`, or `required`
- `non_side_effectful`
- `known_safe_inspect`
- `requests_network_hint`
- `touches_external_hint`

Key rules:

- `exact_effect_mode` is the primary exact-effect capability declaration.
- `supports_exact_effect_staging` is derived from `exact_effect_mode` and must not be set directly.
- `known_safe_inspect` only makes a tool eligible for safe-inspect policy consideration. It never implies `allow` by itself.
- Missing or weak declarations may still register, but execution must fail closed to `ask`, `approval_unavailable`, or `deny`.
- Runtime analysis may conservatively tighten specific fields such as network, external-path, destructive, or protected-path risk. It does not wholesale replace declared semantics.

### Registration vs execution

Registration acceptance is intentionally looser than execution eligibility:

- A tool may register with weak declarations for compatibility.
- A call still needs stable, canonicalizable arguments and stably recomputable effect semantics before it can enter exact-effect approval.
- `exact_effect_mode="required"` means policy-sensitive calls must either stage as exact effects or fail closed. They never fall back to direct execution.

### Author-facing cutover

Author-facing `analysis_hints` is no longer supported in public registration APIs.

Public extension and MCP registrations must use the formal declaration fields only.
The only remaining `analysis_hints` path is private, runtime-internal, and tightening-only.

Deprecation timeline:

- Deprecated since `v0.3.0`
- Planned removal target `v0.4.0`
- The exact warning and error text is driven by code constants, so these version markers remain the source of truth if release numbering shifts later.

Allowed private runtime-only overrides:

- `requests_network`
- `touches_external`
- `destructive_hint`
- `protected_path_hint`
- `touches_workspace`

Allowed values:

- Only the tightening-direction boolean value `True`
- `False`, `safe`, `allow`, `read_only`, `inspect_only`, and other widening or safe values are rejected

Disallowed legacy hints:

- `risk_class`
- `summary`
- `confidence_score`
- `confidence_band`
- `known_safe_inspect`
- `exact_effect_mode`
- `supports_exact_effect_staging`

Representative alias or equivalent examples that are also rejected:

- `safe`
- `allow`
- `read_only`
- `inspect_only`
- `stageable`
- `approval_supported`
- `exact_effect_supported`
- `confidence`
- `safety_score`
- `display_summary`

If an author-facing registration tries to pass `analysis_hints`, registration is rejected and the caller must migrate to the formal declaration fields.

### Precedence

The registry combines semantics in this order:

1. Explicit declarations
2. Legacy compatibility tightening
3. Runtime-discovered conservative tightening

This means:

- Declarations are the primary source of intent.
- Legacy hints can only make a call riskier, never safer.
- Runtime signals can flip individual fields such as `requests_network=True` or `known_safe_inspect=False` when higher risk is detected.

## Removal readiness

The removal-readiness checklist is shared between code, doctor output, and tests. Current criteria are:

- No author-facing legacy analysis_hints remain in runtime metadata.
- Primary dynamic-tool semantics come from formal declarations only.
- Only private runtime-internal risk overrides may remain, and they do not count as author migration blockers.
- Examples, docs, and AGENTS guidance use formal declarations only for public registrations.

Use the doctor command to inspect current status:

- `pp-agent capabilities legacy-hints --workspace <path>`
- `pp-agent capabilities legacy-hints --json --workspace <path>`
- `pp-agent capabilities legacy-hints --strict --workspace <path>`

Readiness source of truth:

- Runtime metadata is authoritative.
- Static scanning is advisory only.
- Author-facing legacy usage is a removal blocker and fails `--strict`.
- Runtime-internal overrides are reported separately and do not block author migration readiness by default.

## Examples

### 1. Safe inspect tool

```python
api.register_tool(
    name="repo_query",
    description="Inspect local repository metadata",
    handler=handle_repo_query,
    parameters={"type": "object", "properties": {"query": {"type": "string"}}},
    exact_effect_mode="auto",
    non_side_effectful=True,
    known_safe_inspect=True,
    requests_network_hint=False,
    touches_external_hint=False,
)
```

Notes:

- This only makes the tool eligible for safe-inspect policy consideration.
- If runtime later detects network or external-path behavior, the call is tightened back to `ask` or fail-closed.

### 2. Staged side-effectful tool

```python
api.register_tool(
    name="publish_report",
    description="Generate and write a report into the workspace",
    handler=handle_publish_report,
    parameters={"type": "object", "properties": {"name": {"type": "string"}}},
    exact_effect_mode="required",
    non_side_effectful=False,
    known_safe_inspect=False,
    requests_network_hint=False,
    touches_external_hint=False,
)
```

Notes:

- Policy-sensitive calls must stage as exact effects before host approval.
- If the arguments or effect cannot be represented stably, the call becomes `approval_unavailable`.

### 3. Unstable tool that must fail closed

```python
api.register_tool(
    name="opaque_bridge",
    description="Proxy opaque actions through external runtime context",
    handler=handle_opaque_bridge,
    parameters={"type": "object", "properties": {"payload": {}}},
    exact_effect_mode="required",
    non_side_effectful=False,
    known_safe_inspect=False,
    requests_network_hint=True,
    touches_external_hint=False,
)
```

Notes:

- If the call depends on unstable or non-canonicalizable payloads, it cannot stage as an exact effect.
- Because `exact_effect_mode="required"` forbids direct fallback, these calls fail closed with `approval_unavailable`.

### 4. MCP example

```python
api.register_tool(
    name="fetch_article",
    description="Fetch a remote article summary",
    handler=handle_fetch_article,
    parameters={"type": "object", "properties": {"url": {"type": "string"}}},
    category="mcp",
    exact_effect_mode="auto",
    non_side_effectful=False,
    known_safe_inspect=False,
    requests_network_hint=True,
    touches_external_hint=False,
)
```

## Migration guidance

Use this historical old-to-new mapping when migrating older code:

| Old legacy hint | New declaration / behavior | Example |
| --- | --- | --- |
| `analysis_hints["known_safe_inspect"]` | `known_safe_inspect=True` and `non_side_effectful=True` | Replace with `known_safe_inspect=True, non_side_effectful=True` |
| `analysis_hints["exact_effect_mode"]` | `exact_effect_mode="auto" | "required" | "none"` | Replace with `exact_effect_mode="required"` |
| `analysis_hints["summary"]` | Remove it; summary is generated by stable analysis | Delete the hint and rely on generated preview text |
| `analysis_hints["risk_class"]` | Remove it; risk class is derived from declarations and runtime analysis | Delete the hint and provide explicit risk declarations instead |
| `analysis_hints["confidence_score"]` / `["confidence_band"]` | Remove them; confidence is derived by shared analysis | Delete the hint entirely |
| `analysis_hints["requests_network"] = True` | Prefer `requests_network_hint=True` | Replace with `requests_network_hint=True`; legacy `True` is still compatibility-only during migration |

General guidance:

- Move any previous `analysis_hints` safe or summary declarations into the formal fields above.
- Do not add new author-facing `analysis_hints`; that path is removed.
- Prefer `exact_effect_mode="auto"` when unsure.
- Use `required` only when the tool should stage exact effects for policy-sensitive calls and the call shape is stable enough to recompute.

