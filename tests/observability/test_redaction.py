from pp_agent.observability.redaction import redact_mapping, safe_preview, sanitize_tool_args


def test_redaction_masks_sensitive_keys():
    data = redact_mapping({"api_key": "abc", "token": "def", "nested": {"password": "pw"}, "ok": "value"})
    assert data["api_key"] == "[REDACTED]"
    assert data["token"] == "[REDACTED]"
    assert data["nested"]["password"] == "[REDACTED]"
    assert data["ok"] == "value"


def test_redaction_keeps_trace_accounting_and_approval_fields():
    data = redact_mapping(
        {
            "total_tokens": 123,
            "estimated_tokens": 456,
            "tool_call_count": 2,
            "approval_token": "tok-visible",
            "access_token": "secret",
        }
    )
    assert data["total_tokens"] == 123
    assert data["estimated_tokens"] == 456
    assert data["tool_call_count"] == 2
    assert data["approval_token"] == "tok-visible"
    assert data["access_token"] == "[REDACTED]"


def test_safe_preview_truncates_and_masks_bearer():
    preview = safe_preview("Authorization: Bearer abcdefghijklmnopqrstuvwxyz", limit=24)
    assert "[REDACTED]" in preview
    assert len(preview) <= 24


def test_sanitize_tool_args_limits_large_content():
    args = sanitize_tool_args({"content": "x" * 3000, "path": "a.txt"})
    assert str(args["content"]).endswith("[truncated]")
    assert args["path"] == "a.txt"
