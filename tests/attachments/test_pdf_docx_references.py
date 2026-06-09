from pathlib import Path

import pytest

from pp_agent.attachments.service import AttachmentService


def test_markdown_search_and_read_chunk_include_source_ref(tmp_path: Path) -> None:
    service = AttachmentService(tmp_path)
    record = service.upload_bytes("s1", "guide.md", b"# Intro\n\nalpha\n\n## Details\n\napproval source reference")

    results = service.search("s1", "approval")
    assert results[0]["source_ref"] == "guide.md > Intro > Details"
    chunk = service.read_chunk("s1", results[0]["chunk_id"])
    assert chunk["chunk"]["source_ref"] == "guide.md > Intro > Details"


def test_pdf_chunks_include_page_source_ref(tmp_path: Path) -> None:
    fitz = pytest.importorskip("fitz")
    pdf_path = tmp_path / "paper.pdf"
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((72, 72), "approval page source")
    doc.save(pdf_path)
    doc.close()

    record = AttachmentService(tmp_path).upload_bytes("s1", "paper.pdf", pdf_path.read_bytes(), content_type="application/pdf")
    assert record.metadata["page_count"] == 1
    result = AttachmentService(tmp_path).search("s1", "approval")[0]
    assert result["source_ref"] == "paper.pdf#page=1"


def test_docx_chunks_include_heading_source_ref(tmp_path: Path) -> None:
    docx = pytest.importorskip("docx")
    path = tmp_path / "report.docx"
    document = docx.Document()
    document.add_heading("Experiment", level=1)
    document.add_heading("Approval", level=2)
    document.add_paragraph("heading source reference")
    document.save(path)

    record = AttachmentService(tmp_path).upload_bytes(
        "s1",
        "report.docx",
        path.read_bytes(),
        content_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    )
    assert record.metadata["headings"]
    result = AttachmentService(tmp_path).search("s1", "reference")[0]
    assert result["source_ref"] == "report.docx > Experiment > Approval"
