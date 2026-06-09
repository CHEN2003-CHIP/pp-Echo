from pp_agent.attachments.chunkers import chunk_code_file, chunk_markdown, chunk_plain_text
from pp_agent.attachments.schema import AttachmentKind


def test_plain_text_chunks_have_line_metadata() -> None:
    chunks = chunk_plain_text("alpha\nbeta\n" * 200, attachment_id="att_abc", session_id="s1", filename="note.txt", kind=AttachmentKind.TEXT)
    assert chunks
    assert chunks[0].chunk_id.startswith("chk_")
    assert chunks[0].line_start == 1


def test_markdown_chunks_keep_headings() -> None:
    chunks = chunk_markdown("# Title\nhello\n## Child\nworld", attachment_id="att_md", session_id="s1", filename="doc.md")
    assert any(chunk.heading_path for chunk in chunks)


def test_code_outline_for_python() -> None:
    chunks, outline = chunk_code_file("import os\nclass A:\n    def run(self):\n        pass\n", attachment_id="att_py", session_id="s1", filename="app.py")
    assert chunks
    assert any(item["name"] == "A" for item in outline)
