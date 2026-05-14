use std::io::{self, BufRead, BufReader, Write};
use std::path::Path;
use std::process::{Child, ChildStdin, ChildStdout, Command, Stdio};
use std::time::{SystemTime, UNIX_EPOCH};

use crate::events::{extract_result_session_id, parse_event, UiEvent};

pub struct RpcClient {
    child: Child,
    stdin: ChildStdin,
    stdout: BufReader<ChildStdout>,
}

#[derive(Debug)]
pub struct RpcResponse {
    pub events: Vec<UiEvent>,
    pub session_id: Option<String>,
    pub result: Option<String>,
}

impl RpcClient {
    pub fn spawn(python: &str, workspace: &Path) -> io::Result<Self> {
        let workspace_arg = workspace.display().to_string();
        let mut child = Command::new(python)
            .args([
                "-m",
                "pp_agent.cli.main",
                "run",
                "--mode",
                "rpc",
                "--workspace",
                &workspace_arg,
            ])
            .stdin(Stdio::piped())
            .stdout(Stdio::piped())
            .spawn()?;
        let stdin = child.stdin.take().ok_or_else(|| io::Error::new(io::ErrorKind::BrokenPipe, "rpc stdin unavailable"))?;
        let stdout = child.stdout.take().ok_or_else(|| io::Error::new(io::ErrorKind::BrokenPipe, "rpc stdout unavailable"))?;
        Ok(Self {
            child,
            stdin,
            stdout: BufReader::new(stdout),
        })
    }

    pub fn run(&mut self, prompt: &str, session_id: Option<&str>) -> io::Result<RpcResponse> {
        let request_id = next_request_id();
        let session_part = session_id.map(|id| format!(r#","session_id":"{}""#, escape_json(id))).unwrap_or_default();
        let request = format!(
            r#"{{"protocol_version":"1","id":"{request_id}","method":"run","params":{{"prompt":"{}"{session_part}}}}}"#,
            escape_json(prompt)
        );
        writeln!(self.stdin, "{request}")?;
        self.stdin.flush()?;

        let mut events = Vec::new();
        let mut session = None;
        let mut result = None;
        loop {
            let mut line = String::new();
            let read = self.stdout.read_line(&mut line)?;
            if read == 0 {
                break;
            }
            if !line.contains(&format!(r#""id":"{request_id}""#)) {
                continue;
            }
            if line.contains(r#""event""#) {
                if let Some(event) = parse_event(&line) {
                    events.push(event);
                }
                continue;
            }
            if line.contains(r#""ok""#) {
                session = extract_result_session_id(&line);
                result = Some(line.trim().to_string());
                break;
            }
        }
        Ok(RpcResponse {
            events,
            session_id: session,
            result,
        })
    }
}

impl Drop for RpcClient {
    fn drop(&mut self) {
        let _ = self.child.kill();
    }
}

fn next_request_id() -> String {
    let millis = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|duration| duration.as_millis())
        .unwrap_or_default();
    format!("req-{millis}")
}

fn escape_json(value: &str) -> String {
    value
        .replace('\\', "\\\\")
        .replace('"', "\\\"")
        .replace('\n', "\\n")
        .replace('\r', "\\r")
        .replace('\t', "\\t")
}
