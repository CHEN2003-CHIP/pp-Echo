# Attachments and Large Files

The attachment system gives pp-Echo a controlled way to work with user-provided files that are too large or too risky to paste into a prompt.

## Flow

1. Web uploads a file with `POST /api/sessions/{session_id}/attachments`.
2. The backend sanitizes the filename, validates size and extension, and writes under `.pp-agent/sessions/<session_id>/attachments/<attachment_id>/`.
3. `AttachmentService` extracts text according to file type.
4. Chunkers add page, line, heading, or table metadata.
5. A local keyword index is written for retrieval.
6. Agent tools expose list, inspect, search, chunk read, line-range read, and code-symbol read operations.
7. The runtime context hook injects only the attachment summary.

## Architectural Boundary

Attachments are session state, not workspace files. Importing an attachment into the workspace is a separate approval-gated feature. The import route stages an `attachment_import` pending action; only `approve_pending_action` copies the original file into the workspace.

Memory ingest is another separate boundary. It must be triggered explicitly, writes capped chunks into Learning memory storage, and preserves `source_type=attachment`, attachment id, chunk id, source ref, tags, and scope.

## Tooling Contract

The model should inspect and search before reading. PDF, DOCX, Markdown, text, and code chunks expose stable `source_ref` values. Code files preserve line metadata and symbol metadata so the Agent can use `search_attachment_symbols`, `read_attachment_symbol`, or `read_attachment_range` after looking at the outline. CSV, JSON, and YAML expose structural metadata through `inspect_attachment`.

Retrieval remains lightweight. Keyword search is the reliable baseline. Optional hybrid retrieval can merge keyword and embedding results, but no external embedding API is called unless an embedding provider is explicitly configured.

## Observability

Attachment upload, extraction, chunking, indexing, search, import preview/request, symbol search/read, memory ingest, read, and delete are named spans/events in the existing TraceInspect pipeline. They reuse redaction and preview limits instead of creating a separate trace system. Trace records metadata, ids, source refs, counts, and snippets; it does not record full uploaded file contents.
