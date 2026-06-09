from pathlib import Path

from pp_agent.attachments.extractors import extract_attachment
from pp_agent.attachments.schema import AttachmentKind


def test_extract_csv_profile(tmp_path: Path) -> None:
    path = tmp_path / "data.csv"
    path.write_text("name,count\nalpha,1\nbeta,2\n", encoding="utf-8")

    text, chunks, metadata = extract_attachment(path, kind=AttachmentKind.CSV, attachment_id="att_csv", session_id="s1", filename="data.csv")

    assert chunks
    assert "columns" in text
    assert metadata["table"]["row_count"] == 2


def test_extract_json_summary(tmp_path: Path) -> None:
    path = tmp_path / "data.json"
    path.write_text('{"items": [1, 2], "name": "demo"}', encoding="utf-8")

    _text, chunks, metadata = extract_attachment(path, kind=AttachmentKind.JSON, attachment_id="att_json", session_id="s1", filename="data.json")

    assert chunks
    assert "items" in metadata["structure"]["top_level_keys"]
