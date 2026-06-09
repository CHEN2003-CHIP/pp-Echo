import { useEffect, useMemo, useState } from "react";
import { Copy, Database, FileDown, FileText, RefreshCw, Search, Trash2 } from "lucide-react";
import { api, AttachmentImportPreview, AttachmentMemoryPreview, AttachmentRecord, AttachmentSearchResult, AttachmentTextRead } from "../../api";

type InspectPayload = {
  attachment: AttachmentRecord;
  metadata: Record<string, unknown>;
};

type ChunkPreview = {
  chunkId: string;
  filename: string;
  source: string;
  text: string;
  truncated: boolean;
};

export function AttachmentPanel({
  sessionId,
  attachments,
  onRefresh,
  onDelete
}: {
  sessionId: string;
  attachments: AttachmentRecord[];
  onRefresh: () => void;
  onDelete: (attachmentId: string) => void;
}) {
  const [selectedId, setSelectedId] = useState("");
  const [inspect, setInspect] = useState<InspectPayload | null>(null);
  const [query, setQuery] = useState("");
  const [filterId, setFilterId] = useState("");
  const [topK, setTopK] = useState(5);
  const [searchMode, setSearchMode] = useState("auto");
  const [results, setResults] = useState<AttachmentSearchResult[]>([]);
  const [chunkPreview, setChunkPreview] = useState<ChunkPreview | null>(null);
  const [textRead, setTextRead] = useState<AttachmentTextRead | null>(null);
  const [targetPath, setTargetPath] = useState("");
  const [overwrite, setOverwrite] = useState(false);
  const [importPreview, setImportPreview] = useState<AttachmentImportPreview | null>(null);
  const [memoryPreview, setMemoryPreview] = useState<AttachmentMemoryPreview | null>(null);
  const [memoryTags, setMemoryTags] = useState("attachment");
  const [loading, setLoading] = useState("");
  const [error, setError] = useState("");

  const selected = useMemo(
    () => attachments.find((attachment) => attachment.attachment_id === selectedId) || attachments[0],
    [attachments, selectedId]
  );

  useEffect(() => {
    if (!selected?.attachment_id || !sessionId) {
      setInspect(null);
      return;
    }
    inspectAttachment(selected.attachment_id);
  }, [selected?.attachment_id, sessionId]);

  async function inspectAttachment(attachmentId: string) {
    setLoading("inspect");
    setError("");
    try {
      setInspect(await api.inspectAttachment(sessionId, attachmentId));
      setSelectedId(attachmentId);
      setTextRead(null);
    } catch (error) {
      setError(error instanceof Error ? error.message : String(error));
    } finally {
      setLoading("");
    }
  }

  async function searchAttachments() {
    if (!query.trim()) return;
    setLoading("search");
    setError("");
    try {
      const payload = await api.searchAttachment(sessionId, query.trim(), filterId || undefined, topK, searchMode);
      setResults(payload.results);
      setChunkPreview(null);
    } catch (error) {
      setError(error instanceof Error ? error.message : String(error));
    } finally {
      setLoading("");
    }
  }

  async function readChunk(result: AttachmentSearchResult) {
    setLoading(result.chunk_id);
    setError("");
    try {
      const payload = await api.readAttachmentChunk(sessionId, result.attachment_id, result.chunk_id);
      setChunkPreview({
        chunkId: result.chunk_id,
        filename: result.filename,
        source: result.source_ref || sourceLabel(result),
        text: payload.text,
        truncated: payload.truncated
      });
    } catch (error) {
      setError(error instanceof Error ? error.message : String(error));
    } finally {
      setLoading("");
    }
  }

  async function readExtractedText(offset = 0) {
    if (!inspect) return;
    setLoading(offset ? "text-more" : "text");
    setError("");
    try {
      const payload = await api.readAttachmentText(sessionId, inspect.attachment.attachment_id, offset, 30000);
      setTextRead((current) =>
        offset && current
          ? { ...payload, text: `${current.text}${payload.text}`, offset: current.offset, returned_chars: current.returned_chars + payload.returned_chars }
          : payload
      );
    } catch (error) {
      setError(error instanceof Error ? error.message : String(error));
    } finally {
      setLoading("");
    }
  }

  function copyPreview() {
    if (!chunkPreview?.text) return;
    navigator.clipboard?.writeText(chunkPreview.text).catch(() => undefined);
  }

  async function previewImport() {
    if (!inspect || !targetPath.trim()) return;
    setLoading("import-preview");
    setError("");
    try {
      setImportPreview(await api.previewAttachmentImport(sessionId, inspect.attachment.attachment_id, targetPath.trim(), overwrite));
    } catch (error) {
      setError(error instanceof Error ? error.message : String(error));
    } finally {
      setLoading("");
    }
  }

  async function confirmImport() {
    if (!inspect || !targetPath.trim()) return;
    setLoading("import");
    setError("");
    try {
      setImportPreview(await api.requestAttachmentImport(sessionId, inspect.attachment.attachment_id, targetPath.trim(), overwrite));
    } catch (error) {
      setError(error instanceof Error ? error.message : String(error));
    } finally {
      setLoading("");
    }
  }

  async function previewMemory() {
    if (!inspect) return;
    setLoading("memory-preview");
    setError("");
    try {
      setMemoryPreview(await api.previewAttachmentMemoryIngest(sessionId, inspect.attachment.attachment_id));
    } catch (error) {
      setError(error instanceof Error ? error.message : String(error));
    } finally {
      setLoading("");
    }
  }

  async function ingestMemory() {
    if (!inspect) return;
    setLoading("memory");
    setError("");
    try {
      const tags = memoryTags.split(",").map((tag) => tag.trim()).filter(Boolean);
      await api.ingestAttachmentMemory(sessionId, inspect.attachment.attachment_id, [], tags.length ? tags : ["attachment"]);
      await previewMemory();
    } catch (error) {
      setError(error instanceof Error ? error.message : String(error));
    } finally {
      setLoading("");
    }
  }

  async function readSymbol(symbol: Record<string, unknown>) {
    if (!inspect || typeof symbol.symbol_id !== "string") return;
    setLoading(symbol.symbol_id);
    setError("");
    try {
      const payload = await api.readAttachmentSymbol(sessionId, inspect.attachment.attachment_id, symbol.symbol_id);
      setChunkPreview({
        chunkId: symbol.symbol_id,
        filename: inspect.attachment.stored_filename,
        source: payload.source_ref,
        text: payload.text,
        truncated: payload.truncated
      });
    } catch (error) {
      setError(error instanceof Error ? error.message : String(error));
    } finally {
      setLoading("");
    }
  }

  return (
    <section className="attachment-panel" aria-label="Attachment panel">
      <header className="attachment-panel-header">
        <div>
          <h3>Attachments</h3>
          <p>{attachments.length} file{attachments.length === 1 ? "" : "s"} in this session</p>
        </div>
        <button type="button" onClick={onRefresh} title="Refresh attachments">
          <RefreshCw size={15} />
        </button>
      </header>

      {error ? <div className="attachment-panel-error">{error}</div> : null}

      <div className="attachment-panel-grid">
        <div className="attachment-panel-list">
          {attachments.length === 0 ? <p className="attachment-panel-empty">No attachments uploaded.</p> : null}
          {attachments.map((attachment) => (
            <button
              className={`attachment-panel-row${attachment.attachment_id === selected?.attachment_id ? " active" : ""}`}
              key={attachment.attachment_id}
              type="button"
              onClick={() => inspectAttachment(attachment.attachment_id)}
            >
              <FileText size={15} />
              <span>
                <strong>{attachment.stored_filename}</strong>
                <small>{attachment.kind} | {formatBytes(attachment.size_bytes)} | {attachment.status} | chunks {String(attachment.metadata?.chunk_count || 0)}</small>
              </span>
              <em>{formatDate(attachment.created_at)}</em>
            </button>
          ))}
        </div>

        <div className="attachment-panel-detail">
          {inspect ? (
            <>
              <div className="attachment-detail-title">
                <div>
                  <h4>{inspect.attachment.stored_filename}</h4>
                  <p>{inspect.attachment.kind} | {inspect.attachment.status}</p>
                </div>
                <button type="button" onClick={() => onDelete(inspect.attachment.attachment_id)} title="Delete attachment">
                  <Trash2 size={14} />
                </button>
              </div>
              <p className="attachment-preview">{inspect.attachment.text_preview || inspect.attachment.error || "No preview available."}</p>
              <div className="attachment-text-actions">
                <small>
                  Preview only | text {formatNumber(inspect.metadata.text_length)} chars | chunks {String(inspect.metadata.chunk_count || 0)}
                </small>
                <button type="button" onClick={() => readExtractedText(0)} disabled={loading === "text"} title="Read extracted text">
                  <FileText size={14} />
                  Read text
                </button>
              </div>
              {textRead ? (
                <div className="attachment-chunk-preview">
                  <header>
                    <div>
                      <strong>Extracted text</strong>
                      <span>{textRead.returned_chars} / {textRead.text_length} chars{textRead.truncated ? " | more available" : ""}</span>
                    </div>
                    {textRead.truncated && textRead.next_offset != null ? (
                      <button type="button" onClick={() => readExtractedText(textRead.next_offset || 0)} disabled={loading === "text-more"} title="Read next text range">
                        Continue
                      </button>
                    ) : null}
                  </header>
                  <pre>{textRead.text}</pre>
                </div>
              ) : null}
              <MetadataBlock metadata={inspect.metadata} onSymbolClick={readSymbol} />
              <div className="attachment-actions">
                <div>
                  <strong>Import to Workspace</strong>
                  <div className="attachment-action-row">
                    <input value={targetPath} onChange={(event) => setTargetPath(event.target.value)} placeholder="docs/uploaded/spec.md" />
                    <label><input type="checkbox" checked={overwrite} onChange={(event) => setOverwrite(event.target.checked)} /> overwrite</label>
                    <button type="button" onClick={previewImport} disabled={!targetPath.trim() || loading === "import-preview"} title="Preview import"><FileDown size={14} /></button>
                    <button type="button" onClick={confirmImport} disabled={!targetPath.trim() || loading === "import"}>Confirm</button>
                  </div>
                  {importPreview ? <small>{importPreview.target_path} | overwrite {String(importPreview.would_overwrite)} | {importPreview.token ? `approval ${importPreview.token}` : importPreview.sha256.slice(0, 12)}</small> : null}
                </div>
                <div>
                  <strong>Ingest to Memory</strong>
                  <div className="attachment-action-row">
                    <input value={memoryTags} onChange={(event) => setMemoryTags(event.target.value)} placeholder="attachment,paper" />
                    <button type="button" onClick={previewMemory} disabled={loading === "memory-preview"} title="Preview memory ingest"><Database size={14} /></button>
                    <button type="button" onClick={ingestMemory} disabled={loading === "memory"}>Ingest</button>
                  </div>
                  {memoryPreview ? <small>{memoryPreview.chunk_count} chunks | {memoryPreview.estimated_memory_items} memory items</small> : null}
                </div>
              </div>
            </>
          ) : (
            <p className="attachment-panel-empty">{loading === "inspect" ? "Loading inspect result..." : "Select an attachment to inspect."}</p>
          )}
        </div>
      </div>

      <div className="attachment-search">
        <select value={filterId} onChange={(event) => setFilterId(event.target.value)}>
          <option value="">All attachments</option>
          {attachments.map((attachment) => (
            <option value={attachment.attachment_id} key={attachment.attachment_id}>
              {attachment.stored_filename}
            </option>
          ))}
        </select>
        <input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Search attachment content" />
        <select value={searchMode} onChange={(event) => setSearchMode(event.target.value)}>
          <option value="auto">auto</option>
          <option value="keyword">keyword</option>
          <option value="hybrid">hybrid</option>
        </select>
        <input min={1} max={20} type="number" value={topK} onChange={(event) => setTopK(Number(event.target.value) || 5)} />
        <button type="button" onClick={searchAttachments} disabled={!query.trim() || loading === "search"}>
          <Search size={14} />
        </button>
      </div>

      <div className="attachment-results">
        {results.map((result) => (
          <button className="attachment-result" type="button" key={result.chunk_id} onClick={() => readChunk(result)}>
            <strong>{result.filename}</strong>
            <span>{result.source_ref || sourceLabel(result)} | score {result.score.toFixed(1)}</span>
            <p>{result.snippet}</p>
          </button>
        ))}
      </div>

      {chunkPreview ? (
        <div className="attachment-chunk-preview">
          <header>
            <div>
              <strong>{chunkPreview.filename}</strong>
              <span>{chunkPreview.chunkId} | {chunkPreview.source}{chunkPreview.truncated ? " | truncated" : ""}</span>
            </div>
            <button type="button" onClick={copyPreview} title="Copy chunk preview">
              <Copy size={14} />
            </button>
          </header>
          <pre>{chunkPreview.text}</pre>
        </div>
      ) : null}
    </section>
  );
}

function MetadataBlock({ metadata, onSymbolClick }: { metadata: Record<string, unknown>; onSymbolClick: (symbol: Record<string, unknown>) => void }) {
  const outline = Array.isArray(metadata.outline) ? metadata.outline : [];
  const headings = Array.isArray(metadata.headings) ? metadata.headings : [];
  const table = typeof metadata.table === "object" && metadata.table ? metadata.table as Record<string, unknown> : null;
  const structure = typeof metadata.structure === "object" && metadata.structure ? metadata.structure as Record<string, unknown> : null;

  return (
    <div className="attachment-metadata">
      {outline.length > 0 ? <MetadataList title="Symbols" items={outline.slice(0, 12)} onItemClick={onSymbolClick} /> : null}
      {headings.length > 0 ? <MetadataList title="Headings" items={headings.slice(0, 12)} /> : null}
      {table ? <MetadataJson title="Table schema" value={table} /> : null}
      {structure ? <MetadataJson title="Structure" value={structure} /> : null}
      {typeof metadata.page_count === "number" ? <p>Pages: {metadata.page_count}</p> : null}
    </div>
  );
}

function MetadataList({ title, items, onItemClick }: { title: string; items: unknown[]; onItemClick?: (item: Record<string, unknown>) => void }) {
  return (
    <div>
      <strong>{title}</strong>
      <ul>
        {items.map((item, index) => (
          <li key={index}>
            {item && typeof item === "object" && onItemClick ? (
              <button type="button" onClick={() => onItemClick(item as Record<string, unknown>)}>{formatMetadataItem(item)}</button>
            ) : (
              formatMetadataItem(item)
            )}
          </li>
        ))}
      </ul>
    </div>
  );
}

function MetadataJson({ title, value }: { title: string; value: Record<string, unknown> }) {
  return (
    <div>
      <strong>{title}</strong>
      <pre>{JSON.stringify(value, null, 2)}</pre>
    </div>
  );
}

function formatMetadataItem(item: unknown) {
  if (Array.isArray(item)) return item.join(" > ");
  if (item && typeof item === "object") {
    const record = item as Record<string, unknown>;
    const name = record.name || record.kind || "item";
    const line = record.line || record.line_start;
    const end = record.end_line || record.line_end;
    return `${String(record.kind || "symbol")} ${String(name)}${line ? ` | lines ${line}${end ? `-${end}` : ""}` : ""}`;
  }
  return String(item);
}

function sourceLabel(result: AttachmentSearchResult) {
  if (result.page_start) return `page ${result.page_start}${result.page_end && result.page_end !== result.page_start ? `-${result.page_end}` : ""}`;
  if (result.line_start) return `lines ${result.line_start}${result.line_end && result.line_end !== result.line_start ? `-${result.line_end}` : ""}`;
  return result.match_type;
}

function formatBytes(value?: number) {
  if (!value) return "0 B";
  if (value < 1024) return `${value} B`;
  if (value < 1024 * 1024) return `${(value / 1024).toFixed(1)} KB`;
  return `${(value / 1024 / 1024).toFixed(1)} MB`;
}

function formatNumber(value: unknown) {
  return typeof value === "number" ? value.toLocaleString() : "0";
}

function formatDate(value?: number) {
  if (!value) return "";
  return new Date(value * 1000).toLocaleDateString();
}
