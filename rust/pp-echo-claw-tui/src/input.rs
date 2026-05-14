use std::io::{self, Write};

#[derive(Debug, Clone, PartialEq, Eq)]
pub enum InputAction {
    Prompt(String),
    Help,
    Status,
    Eval,
    Sessions,
    Permissions,
    Diff,
    Empty,
    Exit,
}

pub struct ReplInput {
    history: Vec<String>,
}

impl ReplInput {
    pub fn new() -> Self {
        Self { history: Vec::new() }
    }

    pub fn read_action(&mut self, session_id: Option<&str>) -> io::Result<InputAction> {
        let prompt = match session_id {
            Some(id) => format!("pp-echo[{id:.8}]> "),
            None => "pp-echo> ".to_string(),
        };
        print!("{prompt}");
        io::stdout().flush()?;
        let mut line = String::new();
        io::stdin().read_line(&mut line)?;
        let value = line.trim().to_string();
        if value.is_empty() {
            return Ok(InputAction::Empty);
        }
        self.history.push(value.clone());
        Ok(action_from_text(&value))
    }
}

pub fn action_from_text(value: &str) -> InputAction {
    match value.trim() {
        "/exit" | "/quit" => InputAction::Exit,
        "/help" => InputAction::Help,
        "/status" => InputAction::Status,
        "/eval" => InputAction::Eval,
        "/sessions" => InputAction::Sessions,
        "/permissions" => InputAction::Permissions,
        "/diff" => InputAction::Diff,
        "" => InputAction::Empty,
        other => InputAction::Prompt(other.to_string()),
    }
}

pub fn slash_completions(prefix: &str) -> Vec<&'static str> {
    const COMMANDS: [&str; 8] = ["/help", "/status", "/eval", "/permissions", "/sessions", "/diff", "/exit", "/quit"];
    COMMANDS
        .iter()
        .copied()
        .filter(|command| command.starts_with(prefix))
        .collect()
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn matches_slash_commands() {
        assert_eq!(action_from_text("/status"), InputAction::Status);
        assert_eq!(slash_completions("/e"), vec!["/eval", "/exit"]);
    }
}

