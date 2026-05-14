mod events;
mod input;
mod render;
mod rpc;

use std::env;
use std::io::{self, Write};
use std::path::PathBuf;

use input::{InputAction, ReplInput};
use render::TerminalRenderer;
use rpc::RpcClient;

fn main() -> io::Result<()> {
    let args = Args::parse(env::args().skip(1).collect());
    let mut renderer = TerminalRenderer::default();
    renderer.banner(&args.workspace);

    let mut rpc = RpcClient::spawn(&args.python, &args.workspace)?;
    let mut input = ReplInput::new();
    let mut session_id: Option<String> = None;

    loop {
        match input.read_action(session_id.as_deref())? {
            InputAction::Exit => break,
            InputAction::Empty => continue,
            InputAction::Help => renderer.help(),
            InputAction::Status => renderer.status(session_id.as_deref()),
            InputAction::Eval => renderer.latest_eval_summary(&args.workspace),
            InputAction::Sessions => renderer.sessions_hint(),
            InputAction::Permissions => renderer.permissions_hint(),
            InputAction::Diff => renderer.diff_hint(),
            InputAction::Prompt(prompt) => {
                let response = rpc.run(&prompt, session_id.as_deref())?;
                for event in &response.events {
                    renderer.event(event);
                }
                if let Some(new_session_id) = response.session_id {
                    session_id = Some(new_session_id);
                }
                if let Some(result) = response.result {
                    renderer.result(&result);
                }
                io::stdout().flush()?;
            }
        }
    }

    Ok(())
}

#[derive(Debug)]
struct Args {
    workspace: PathBuf,
    python: String,
}

impl Args {
    fn parse(values: Vec<String>) -> Self {
        let mut workspace = env::current_dir().unwrap_or_else(|_| PathBuf::from("."));
        let mut python = env::var("PYTHON").unwrap_or_else(|_| "python".to_string());
        let mut index = 0;
        while index < values.len() {
            match values[index].as_str() {
                "--workspace" | "-w" => {
                    if let Some(value) = values.get(index + 1) {
                        workspace = PathBuf::from(value);
                        index += 1;
                    }
                }
                "--python" => {
                    if let Some(value) = values.get(index + 1) {
                        python = value.clone();
                        index += 1;
                    }
                }
                _ => {}
            }
            index += 1;
        }
        Self { workspace, python }
    }
}

