# File Attachments and Large File Analysis

pp-Echo supports session-scoped attachments for files that should be available to the Agent without being copied into the workspace or injected wholesale into the prompt.

Uploaded files are saved under `.pp-agent/sessions/<session_id>/attachments/<attachment_id>/`. Each attachment keeps an `original/` file, `manifest.json`, extracted text, `chunks.jsonl`, and a lightweight keyword `index.json`.

## Design

Large files are not directly inserted into model context. The runtime injects only an attachment list and short previews. When the Agent needs content, it must call:

- `list_attachments`
- `inspect_attachment`
- `search_attachment`
- `read_attachment_chunk`
- `read_attachment_range`
- `search_attachment_symbols`
- `read_attachment_symbol`

This keeps prompts small, preserves source metadata, and avoids accidental workspace pollution.

## Upload, Import, and Memory Ingest

Upload stores a file only under the session attachment directory. It does not change the workspace.

Import to Workspace is a separate explicit action. The API first creates an import preview, then stages an `attachment_import` pending action with a stable effect digest. The original file is copied into the workspace only after Approval Gate consumes that pending action.

Ingest to Memory is also explicit. It writes selected or capped attachment chunks into the Learning memory JSONL with source metadata. pp-Echo never auto-ingests every uploaded file.

## File Types

The first implementation supports text, Markdown, log, code, CSV, JSON, and YAML with local parsing and retrieval. PDF and DOCX support is optional through the `attachments` extra. If those packages are missing, upload succeeds to controlled storage but parsing is marked failed with a clear dependency message.

Chunks expose stable source references:

- PDF: `paper.pdf#page=3`
- DOCX or Markdown: `report.docx > Heading > Child heading`
- Code and text: `file.py:L10-L28`

Code attachments also expose symbol metadata for classes, functions, methods, imports, and top-level constants. The Agent can search symbols before reading local code ranges.

Search defaults to `auto`. Keyword search always works. Hybrid search and embedding are optional; when no embedding provider is configured, `auto` and `hybrid` fall back to keyword search with trace metadata explaining the fallback.

Executable and archive-like extensions such as `.exe`, `.dll`, `.bat`, `.ps1`, `.sh`, `.zip`, `.rar`, and `.7z` are rejected by default.

## Observability

Attachment operations record TraceInspect spans when an active trace recorder is available:

- `attachment.upload`
- `attachment.extract`
- `attachment.chunk`
- `attachment.index`
- `attachment.search`
- `attachment.read_chunk`
- `attachment.read_range`
- `attachment.import_preview`
- `attachment.import_requested`
- `attachment.symbol_index`
- `attachment.symbol_search`
- `attachment.read_symbol`
- `attachment.memory_ingest_preview`
- `attachment.memory_ingest`
- `attachment.delete`

Trace payloads store metadata, counts, ids, short previews, and errors. They do not store full uploaded file contents.

## Current Limits

- No OCR.
- No automatic workspace import; import is approval-gated.
- No execution of uploaded scripts.
- No default external embedding calls and no mandatory vector database.
- Memory ingest must be explicit and capped.
- PDF and DOCX parsing require optional dependencies.
