#[derive(Debug, Clone, PartialEq, Eq)]
pub enum UiEvent {
    MessageDelta(String),
    ToolStart { name: String, preview: String },
    ToolEnd { name: String, message: String, error: bool },
    ToolResult { name: String, preview: String },
    ProviderError(String),
    ApprovalPending(String),
    TurnEnd { failed: bool, failure_kind: String },
    Other { event_type: String, message: String },
}

pub fn parse_event(line: &str) -> Option<UiEvent> {
    let event_type = extract_string(line, "\"type\"")?;
    match event_type.as_str() {
        "message_delta" => Some(UiEvent::MessageDelta(extract_string(line, "\"delta\"").unwrap_or_default())),
        "tool_start" => Some(UiEvent::ToolStart {
            name: extract_string(line, "\"tool_name\"").unwrap_or_else(|| "tool".to_string()),
            preview: extract_string(line, "\"args_preview\"").unwrap_or_default(),
        }),
        "tool_result" => Some(UiEvent::ToolResult {
            name: extract_string(line, "\"tool_name\"").unwrap_or_else(|| "tool".to_string()),
            preview: extract_string(line, "\"preview\"").or_else(|| extract_string(line, "\"message\"")).unwrap_or_default(),
        }),
        "tool_end" => Some(UiEvent::ToolEnd {
            name: extract_string(line, "\"tool_name\"").unwrap_or_else(|| "tool".to_string()),
            message: extract_string(line, "\"message\"").unwrap_or_default(),
            error: extract_bool(line, "\"is_error\"").unwrap_or(false),
        }),
        "provider_error" | "error" => Some(UiEvent::ProviderError(extract_string(line, "\"message\"").unwrap_or_default())),
        "planner_gate_pending" => Some(UiEvent::ApprovalPending(extract_string(line, "\"message\"").unwrap_or_default())),
        "turn_end" => Some(UiEvent::TurnEnd {
            failed: line.contains("\"failed\":true"),
            failure_kind: extract_string(line, "\"failure_kind\"").unwrap_or_default(),
        }),
        _ => Some(UiEvent::Other {
            event_type,
            message: extract_string(line, "\"message\"").unwrap_or_default(),
        }),
    }
}

pub fn extract_result_session_id(line: &str) -> Option<String> {
    extract_string(line, "\"session_id\"")
}

pub fn extract_string(source: &str, key: &str) -> Option<String> {
    let key_pos = source.find(key)?;
    let after_key = &source[key_pos + key.len()..];
    let colon = after_key.find(':')?;
    let mut chars = after_key[colon + 1..].chars().peekable();
    while matches!(chars.peek(), Some(ch) if ch.is_whitespace()) {
        chars.next();
    }
    if chars.next()? != '"' {
        return None;
    }
    let mut out = String::new();
    let mut escaped = false;
    for ch in chars {
        if escaped {
            match ch {
                'n' => out.push('\n'),
                'r' => out.push('\r'),
                't' => out.push('\t'),
                '"' => out.push('"'),
                '\\' => out.push('\\'),
                other => out.push(other),
            }
            escaped = false;
            continue;
        }
        if ch == '\\' {
            escaped = true;
            continue;
        }
        if ch == '"' {
            return Some(out);
        }
        out.push(ch);
    }
    None
}

fn extract_bool(source: &str, key: &str) -> Option<bool> {
    let key_pos = source.find(key)?;
    let after_key = &source[key_pos + key.len()..];
    let colon = after_key.find(':')?;
    let value = after_key[colon + 1..].trim_start();
    if value.starts_with("true") {
        Some(true)
    } else if value.starts_with("false") {
        Some(false)
    } else {
        None
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn parses_provider_error() {
        let line = r#"{"protocol_version":"1","id":"1","event":{"type":"provider_error","message":"LLM request failed: SSL"}}"#;
        assert_eq!(parse_event(line), Some(UiEvent::ProviderError("LLM request failed: SSL".to_string())));
    }
}

