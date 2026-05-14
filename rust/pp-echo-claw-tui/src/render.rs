use std::fs;
use std::io::{self, Write};
use std::path::Path;

use crate::events::UiEvent;

const RESET: &str = "\x1b[0m";
const DIM: &str = "\x1b[2m";
const BOLD: &str = "\x1b[1m";
const RED: &str = "\x1b[31m";
const GREEN: &str = "\x1b[32m";
const YELLOW: &str = "\x1b[33m";
const BLUE: &str = "\x1b[34m";
const CYAN: &str = "\x1b[36m";

#[derive(Debug, Default)]
pub struct TerminalRenderer {
    markdown_buffer: String,
}

impl TerminalRenderer {
    pub fn banner(&mut self, workspace: &Path) {
        println!("{BOLD}{CYAN}pp-Echo claw-tui{RESET} {DIM}workspace={} {RESET}", workspace.display());
        println!("{DIM}Commands: /help /status /eval /permissions /sessions /diff /exit{RESET}\n");
    }

    pub fn help(&self) {
        println!("{}", tool_card("help", "Available commands:\n/status\n/eval\n/permissions\n/sessions\n/diff\n/exit", false));
    }

    pub fn status(&self, session_id: Option<&str>) {
        let body = format!("session: {}\nbackend: pp-agent stdio rpc", session_id.unwrap_or("-"));
        println!("{}", tool_card("status", &body, false));
    }

    pub fn sessions_hint(&self) {
        println!("{}", tool_card("sessions", "Session listing is available from Python CLI: pp-agent sessions tree", false));
    }

    pub fn permissions_hint(&self) {
        println!("{}", tool_card("permissions", "Permission mode is enforced by Python ToolPolicy over stdio RPC.", false));
    }

    pub fn diff_hint(&self) {
        println!("{}", tool_card("diff", "Diff blocks are rendered from tool results when present.", false));
    }

    pub fn latest_eval_summary(&self, workspace: &Path) {
        let runs = workspace.join(".pp-agent").join("evals").join("runs");
        let Ok(entries) = fs::read_dir(&runs) else {
            println!("{}", tool_card("eval", "No eval summary directory found.", true));
            return;
        };
        let mut summaries = entries
            .filter_map(Result::ok)
            .map(|entry| entry.path())
            .filter(|path| path.file_name().and_then(|name| name.to_str()).is_some_and(|name| name.ends_with("-summary.json")))
            .collect::<Vec<_>>();
        summaries.sort_by_key(|path| fs::metadata(path).and_then(|metadata| metadata.modified()).ok());
        let Some(path) = summaries.pop() else {
            println!("{}", tool_card("eval", "No eval summaries found.", true));
            return;
        };
        let body = fs::read_to_string(&path).unwrap_or_else(|err| format!("Failed to read {}: {err}", path.display()));
        println!("{}", tool_card("eval summary", &collapse(&body, 20), false));
    }

    pub fn event(&mut self, event: &UiEvent) {
        match event {
            UiEvent::MessageDelta(delta) => {
                self.markdown_buffer.push_str(delta);
                print!("{}", render_markdown(delta));
                let _ = io::stdout().flush();
            }
            UiEvent::ToolStart { name, preview } => {
                println!("{}", tool_card(&format!("running {name}"), preview, false));
            }
            UiEvent::ToolResult { name, preview } => {
                println!("{}", tool_card(&format!("result {name}"), &render_diff_or_text(preview), false));
            }
            UiEvent::ToolEnd { name, message, error } => {
                println!("{}", tool_card(&format!("{} {name}", if *error { "failed" } else { "done" }), message, *error));
            }
            UiEvent::ProviderError(message) => {
                println!("{}", tool_card("provider_error", message, true));
            }
            UiEvent::ApprovalPending(message) => {
                println!("{}", tool_card("approval required", message, true));
            }
            UiEvent::TurnEnd { failed, failure_kind } => {
                if *failed {
                    println!("{}", tool_card("turn failed", failure_kind, true));
                }
            }
            UiEvent::Other { event_type, message } => {
                if !message.is_empty() {
                    println!("{}", tool_card(event_type, message, false));
                }
            }
        }
    }

    pub fn result(&mut self, raw_result: &str) {
        if !raw_result.trim().is_empty() {
            println!("{}", tool_card("result", &collapse(raw_result, 15), false));
        }
        self.markdown_buffer.clear();
    }
}

pub fn render_markdown(markdown: &str) -> String {
    let mut out = String::new();
    let mut in_code = false;
    let mut code_label = String::new();
    for raw_line in normalize_nested_fences(markdown).lines() {
        let line = raw_line.trim_end();
        if line.starts_with("```") || line.starts_with("~~~") {
            if in_code {
                out.push_str(&format!("{DIM}╰─{RESET}\n"));
                in_code = false;
                code_label.clear();
            } else {
                code_label = line.trim_start_matches('`').trim_start_matches('~').trim().to_string();
                if code_label.is_empty() {
                    code_label = "code".to_string();
                }
                out.push_str(&format!("{DIM}╭─ {code_label}{RESET}\n"));
                in_code = true;
            }
            continue;
        }
        if in_code {
            out.push_str(&format!("\x1b[48;5;236m{line}{RESET}\n"));
        } else if let Some(text) = line.strip_prefix("# ") {
            out.push_str(&format!("{BOLD}{CYAN}{text}{RESET}\n"));
        } else if let Some(text) = line.strip_prefix("## ") {
            out.push_str(&format!("{BOLD}{text}{RESET}\n"));
        } else if let Some(text) = line.strip_prefix("> ") {
            out.push_str(&format!("{DIM}│ {text}{RESET}\n"));
        } else if line.starts_with("- ") || line.starts_with("* ") {
            out.push_str(&format!("  • {}\n", &line[2..]));
        } else {
            out.push_str(line);
            out.push('\n');
        }
    }
    out
}

pub fn tool_card(title: &str, body: &str, error: bool) -> String {
    let color = if error { RED } else { BLUE };
    let title_line = format!("{color}╭─ {title} ─╮{RESET}");
    let footer = format!("{color}╰─{RESET}");
    let body = collapse(body, 15)
        .lines()
        .map(|line| format!("{color}│{RESET} {line}"))
        .collect::<Vec<_>>()
        .join("\n");
    format!("{title_line}\n{body}\n{footer}")
}

pub fn render_diff_or_text(text: &str) -> String {
    text.lines()
        .map(|line| {
            if line.starts_with('+') && !line.starts_with("+++") {
                format!("{GREEN}{line}{RESET}")
            } else if line.starts_with('-') && !line.starts_with("---") {
                format!("{RED}{line}{RESET}")
            } else if line.starts_with("@@") {
                format!("{CYAN}{line}{RESET}")
            } else {
                line.to_string()
            }
        })
        .collect::<Vec<_>>()
        .join("\n")
}

pub fn collapse(text: &str, max_lines: usize) -> String {
    let lines = text.lines().collect::<Vec<_>>();
    if lines.len() <= max_lines {
        return text.to_string();
    }
    let mut out = lines[..max_lines].join("\n");
    out.push_str(&format!("\n{YELLOW}... collapsed {} more lines ...{RESET}", lines.len() - max_lines));
    out
}

pub fn normalize_nested_fences(markdown: &str) -> String {
    // Lightweight equivalent of claw-code's nested fence normalization:
    // if a labeled triple-backtick block contains another triple fence,
    // upgrade only the outer pair to four backticks.
    let mut out = String::new();
    let mut in_labeled_fence = false;
    let mut buffer: Vec<&str> = Vec::new();
    for line in markdown.lines() {
        if !in_labeled_fence && line.starts_with("```") && line.trim().len() > 3 {
            in_labeled_fence = true;
            buffer.clear();
            buffer.push(line);
            continue;
        }
        if in_labeled_fence {
            buffer.push(line);
            if line.trim() == "```" {
                let has_nested = buffer[1..buffer.len().saturating_sub(1)].iter().any(|item| item.trim_start().starts_with("```"));
                for (index, item) in buffer.iter().enumerate() {
                    if has_nested && (index == 0 || index + 1 == buffer.len()) {
                        out.push('`');
                    }
                    out.push_str(item);
                    out.push('\n');
                }
                in_labeled_fence = false;
            }
            continue;
        }
        out.push_str(line);
        out.push('\n');
    }
    if in_labeled_fence {
        out.push_str(&buffer.join("\n"));
    }
    out
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn renders_tool_card() {
        let rendered = tool_card("read_file", "ok", false);
        assert!(rendered.contains("╭─ read_file ─╮"));
    }

    #[test]
    fn colors_diff_lines() {
        let rendered = render_diff_or_text("+new\n-old\n@@ hunk");
        assert!(rendered.contains(GREEN));
        assert!(rendered.contains(RED));
        assert!(rendered.contains(CYAN));
    }

    #[test]
    fn collapses_long_output() {
        let text = (0..20).map(|i| i.to_string()).collect::<Vec<_>>().join("\n");
        assert!(collapse(&text, 5).contains("collapsed 15 more lines"));
    }
}

