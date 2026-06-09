from pp_agent.attachments.code_index import build_symbol_index, search_symbols


def test_python_symbol_index_extracts_class_function_method_lines() -> None:
    text = """import os

class AgentRuntime:
    \"\"\"runtime docs\"\"\"
    def run_turn(self):
        return os.getcwd()

def build_context():
    return {}
"""

    symbols = build_symbol_index(text, attachment_id="att_code", filename="runtime.py")
    names = {symbol.name: symbol for symbol in symbols}

    assert names["AgentRuntime"].kind == "class"
    assert names["AgentRuntime"].line_start == 3
    assert names["run_turn"].parent == "AgentRuntime"
    assert names["run_turn"].line_start == 5
    assert names["build_context"].kind == "function"
    assert search_symbols(symbols, "AgentRuntime")[0]["name"] == "AgentRuntime"


def test_js_symbol_index_uses_lightweight_heuristic() -> None:
    text = """export class AttachmentPanel {
  render() {}
}
const readAttachment = () => true
"""

    symbols = build_symbol_index(text, attachment_id="att_js", filename="panel.ts")

    assert any(symbol.name == "AttachmentPanel" for symbol in symbols)
    assert any(symbol.name == "readAttachment" for symbol in symbols)
