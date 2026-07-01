"use strict";
Object.defineProperty(exports, "__esModule", { value: true });
exports.AttachmentPanel = AttachmentPanel;
const jsx_runtime_1 = require("react/jsx-runtime");
const react_1 = require("react");
const lucide_react_1 = require("lucide-react");
const api_1 = require("../../api");
function AttachmentPanel({ sessionId, attachments, onRefresh, onDelete }) {
    const [selectedId, setSelectedId] = (0, react_1.useState)("");
    const [inspect, setInspect] = (0, react_1.useState)(null);
    const [query, setQuery] = (0, react_1.useState)("");
    const [filterId, setFilterId] = (0, react_1.useState)("");
    const [topK, setTopK] = (0, react_1.useState)(5);
    const [searchMode, setSearchMode] = (0, react_1.useState)("auto");
    const [results, setResults] = (0, react_1.useState)([]);
    const [chunkPreview, setChunkPreview] = (0, react_1.useState)(null);
    const [textRead, setTextRead] = (0, react_1.useState)(null);
    const [targetPath, setTargetPath] = (0, react_1.useState)("");
    const [overwrite, setOverwrite] = (0, react_1.useState)(false);
    const [importPreview, setImportPreview] = (0, react_1.useState)(null);
    const [memoryPreview, setMemoryPreview] = (0, react_1.useState)(null);
    const [memoryTags, setMemoryTags] = (0, react_1.useState)("attachment");
    const [loading, setLoading] = (0, react_1.useState)("");
    const [error, setError] = (0, react_1.useState)("");
    const selected = (0, react_1.useMemo)(() => attachments.find((attachment) => attachment.attachment_id === selectedId) || attachments[0], [attachments, selectedId]);
    (0, react_1.useEffect)(() => {
        if (!selected?.attachment_id || !sessionId) {
            setInspect(null);
            return;
        }
        inspectAttachment(selected.attachment_id);
    }, [selected?.attachment_id, sessionId]);
    async function inspectAttachment(attachmentId) {
        setLoading("inspect");
        setError("");
        try {
            setInspect(await api_1.api.inspectAttachment(sessionId, attachmentId));
            setSelectedId(attachmentId);
            setTextRead(null);
        }
        catch (error) {
            setError(error instanceof Error ? error.message : String(error));
        }
        finally {
            setLoading("");
        }
    }
    async function searchAttachments() {
        if (!query.trim())
            return;
        setLoading("search");
        setError("");
        try {
            const payload = await api_1.api.searchAttachment(sessionId, query.trim(), filterId || undefined, topK, searchMode);
            setResults(payload.results);
            setChunkPreview(null);
        }
        catch (error) {
            setError(error instanceof Error ? error.message : String(error));
        }
        finally {
            setLoading("");
        }
    }
    async function readChunk(result) {
        setLoading(result.chunk_id);
        setError("");
        try {
            const payload = await api_1.api.readAttachmentChunk(sessionId, result.attachment_id, result.chunk_id);
            setChunkPreview({
                chunkId: result.chunk_id,
                filename: result.filename,
                source: result.source_ref || sourceLabel(result),
                text: payload.text,
                truncated: payload.truncated
            });
        }
        catch (error) {
            setError(error instanceof Error ? error.message : String(error));
        }
        finally {
            setLoading("");
        }
    }
    async function readExtractedText(offset = 0) {
        if (!inspect)
            return;
        setLoading(offset ? "text-more" : "text");
        setError("");
        try {
            const payload = await api_1.api.readAttachmentText(sessionId, inspect.attachment.attachment_id, offset, 30000);
            setTextRead((current) => offset && current
                ? { ...payload, text: `${current.text}${payload.text}`, offset: current.offset, returned_chars: current.returned_chars + payload.returned_chars }
                : payload);
        }
        catch (error) {
            setError(error instanceof Error ? error.message : String(error));
        }
        finally {
            setLoading("");
        }
    }
    function copyPreview() {
        if (!chunkPreview?.text)
            return;
        navigator.clipboard?.writeText(chunkPreview.text).catch(() => undefined);
    }
    async function previewImport() {
        if (!inspect || !targetPath.trim())
            return;
        setLoading("import-preview");
        setError("");
        try {
            setImportPreview(await api_1.api.previewAttachmentImport(sessionId, inspect.attachment.attachment_id, targetPath.trim(), overwrite));
        }
        catch (error) {
            setError(error instanceof Error ? error.message : String(error));
        }
        finally {
            setLoading("");
        }
    }
    async function confirmImport() {
        if (!inspect || !targetPath.trim())
            return;
        setLoading("import");
        setError("");
        try {
            setImportPreview(await api_1.api.requestAttachmentImport(sessionId, inspect.attachment.attachment_id, targetPath.trim(), overwrite));
        }
        catch (error) {
            setError(error instanceof Error ? error.message : String(error));
        }
        finally {
            setLoading("");
        }
    }
    async function previewMemory() {
        if (!inspect)
            return;
        setLoading("memory-preview");
        setError("");
        try {
            setMemoryPreview(await api_1.api.previewAttachmentMemoryIngest(sessionId, inspect.attachment.attachment_id));
        }
        catch (error) {
            setError(error instanceof Error ? error.message : String(error));
        }
        finally {
            setLoading("");
        }
    }
    async function ingestMemory() {
        if (!inspect)
            return;
        setLoading("memory");
        setError("");
        try {
            const tags = memoryTags.split(",").map((tag) => tag.trim()).filter(Boolean);
            await api_1.api.ingestAttachmentMemory(sessionId, inspect.attachment.attachment_id, [], tags.length ? tags : ["attachment"]);
            await previewMemory();
        }
        catch (error) {
            setError(error instanceof Error ? error.message : String(error));
        }
        finally {
            setLoading("");
        }
    }
    async function readSymbol(symbol) {
        if (!inspect || typeof symbol.symbol_id !== "string")
            return;
        setLoading(symbol.symbol_id);
        setError("");
        try {
            const payload = await api_1.api.readAttachmentSymbol(sessionId, inspect.attachment.attachment_id, symbol.symbol_id);
            setChunkPreview({
                chunkId: symbol.symbol_id,
                filename: inspect.attachment.stored_filename,
                source: payload.source_ref,
                text: payload.text,
                truncated: payload.truncated
            });
        }
        catch (error) {
            setError(error instanceof Error ? error.message : String(error));
        }
        finally {
            setLoading("");
        }
    }
    return ((0, jsx_runtime_1.jsxs)("section", { className: "attachment-panel", "aria-label": "Attachment panel", children: [(0, jsx_runtime_1.jsxs)("header", { className: "attachment-panel-header", children: [(0, jsx_runtime_1.jsxs)("div", { children: [(0, jsx_runtime_1.jsx)("h3", { children: "Attachments" }), (0, jsx_runtime_1.jsxs)("p", { children: [attachments.length, " file", attachments.length === 1 ? "" : "s", " in this session"] })] }), (0, jsx_runtime_1.jsx)("button", { type: "button", onClick: onRefresh, title: "Refresh attachments", children: (0, jsx_runtime_1.jsx)(lucide_react_1.RefreshCw, { size: 15 }) })] }), error ? (0, jsx_runtime_1.jsx)("div", { className: "attachment-panel-error", children: error }) : null, (0, jsx_runtime_1.jsxs)("div", { className: "attachment-panel-grid", children: [(0, jsx_runtime_1.jsxs)("div", { className: "attachment-panel-list", children: [attachments.length === 0 ? (0, jsx_runtime_1.jsx)("p", { className: "attachment-panel-empty", children: "No attachments uploaded." }) : null, attachments.map((attachment) => ((0, jsx_runtime_1.jsxs)("button", { className: `attachment-panel-row${attachment.attachment_id === selected?.attachment_id ? " active" : ""}`, type: "button", onClick: () => inspectAttachment(attachment.attachment_id), children: [(0, jsx_runtime_1.jsx)(lucide_react_1.FileText, { size: 15 }), (0, jsx_runtime_1.jsxs)("span", { children: [(0, jsx_runtime_1.jsx)("strong", { children: attachment.stored_filename }), (0, jsx_runtime_1.jsxs)("small", { children: [attachment.kind, " | ", formatBytes(attachment.size_bytes), " | ", attachment.status, " | chunks ", String(attachment.metadata?.chunk_count || 0)] })] }), (0, jsx_runtime_1.jsx)("em", { children: formatDate(attachment.created_at) })] }, attachment.attachment_id)))] }), (0, jsx_runtime_1.jsx)("div", { className: "attachment-panel-detail", children: inspect ? ((0, jsx_runtime_1.jsxs)(jsx_runtime_1.Fragment, { children: [(0, jsx_runtime_1.jsxs)("div", { className: "attachment-detail-title", children: [(0, jsx_runtime_1.jsxs)("div", { children: [(0, jsx_runtime_1.jsx)("h4", { children: inspect.attachment.stored_filename }), (0, jsx_runtime_1.jsxs)("p", { children: [inspect.attachment.kind, " | ", inspect.attachment.status] })] }), (0, jsx_runtime_1.jsx)("button", { type: "button", onClick: () => onDelete(inspect.attachment.attachment_id), title: "Delete attachment", children: (0, jsx_runtime_1.jsx)(lucide_react_1.Trash2, { size: 14 }) })] }), (0, jsx_runtime_1.jsx)("p", { className: "attachment-preview", children: inspect.attachment.text_preview || inspect.attachment.error || "No preview available." }), (0, jsx_runtime_1.jsxs)("div", { className: "attachment-text-actions", children: [(0, jsx_runtime_1.jsxs)("small", { children: ["Preview only | text ", formatNumber(inspect.metadata.text_length), " chars | chunks ", String(inspect.metadata.chunk_count || 0)] }), (0, jsx_runtime_1.jsxs)("button", { type: "button", onClick: () => readExtractedText(0), disabled: loading === "text", title: "Read extracted text", children: [(0, jsx_runtime_1.jsx)(lucide_react_1.FileText, { size: 14 }), "Read text"] })] }), textRead ? ((0, jsx_runtime_1.jsxs)("div", { className: "attachment-chunk-preview", children: [(0, jsx_runtime_1.jsxs)("header", { children: [(0, jsx_runtime_1.jsxs)("div", { children: [(0, jsx_runtime_1.jsx)("strong", { children: "Extracted text" }), (0, jsx_runtime_1.jsxs)("span", { children: [textRead.returned_chars, " / ", textRead.text_length, " chars", textRead.truncated ? " | more available" : ""] })] }), textRead.truncated && textRead.next_offset != null ? ((0, jsx_runtime_1.jsx)("button", { type: "button", onClick: () => readExtractedText(textRead.next_offset || 0), disabled: loading === "text-more", title: "Read next text range", children: "Continue" })) : null] }), (0, jsx_runtime_1.jsx)("pre", { children: textRead.text })] })) : null, (0, jsx_runtime_1.jsx)(MetadataBlock, { metadata: inspect.metadata, onSymbolClick: readSymbol }), (0, jsx_runtime_1.jsxs)("div", { className: "attachment-actions", children: [(0, jsx_runtime_1.jsxs)("div", { children: [(0, jsx_runtime_1.jsx)("strong", { children: "Import to Workspace" }), (0, jsx_runtime_1.jsxs)("div", { className: "attachment-action-row", children: [(0, jsx_runtime_1.jsx)("input", { value: targetPath, onChange: (event) => setTargetPath(event.target.value), placeholder: "docs/uploaded/spec.md" }), (0, jsx_runtime_1.jsxs)("label", { children: [(0, jsx_runtime_1.jsx)("input", { type: "checkbox", checked: overwrite, onChange: (event) => setOverwrite(event.target.checked) }), " overwrite"] }), (0, jsx_runtime_1.jsx)("button", { type: "button", onClick: previewImport, disabled: !targetPath.trim() || loading === "import-preview", title: "Preview import", children: (0, jsx_runtime_1.jsx)(lucide_react_1.FileDown, { size: 14 }) }), (0, jsx_runtime_1.jsx)("button", { type: "button", onClick: confirmImport, disabled: !targetPath.trim() || loading === "import", children: "Confirm" })] }), importPreview ? (0, jsx_runtime_1.jsxs)("small", { children: [importPreview.target_path, " | overwrite ", String(importPreview.would_overwrite), " | ", importPreview.token ? `approval ${importPreview.token}` : importPreview.sha256.slice(0, 12)] }) : null] }), (0, jsx_runtime_1.jsxs)("div", { children: [(0, jsx_runtime_1.jsx)("strong", { children: "Ingest to Memory" }), (0, jsx_runtime_1.jsxs)("div", { className: "attachment-action-row", children: [(0, jsx_runtime_1.jsx)("input", { value: memoryTags, onChange: (event) => setMemoryTags(event.target.value), placeholder: "attachment,paper" }), (0, jsx_runtime_1.jsx)("button", { type: "button", onClick: previewMemory, disabled: loading === "memory-preview", title: "Preview memory ingest", children: (0, jsx_runtime_1.jsx)(lucide_react_1.Database, { size: 14 }) }), (0, jsx_runtime_1.jsx)("button", { type: "button", onClick: ingestMemory, disabled: loading === "memory", children: "Ingest" })] }), memoryPreview ? (0, jsx_runtime_1.jsxs)("small", { children: [memoryPreview.chunk_count, " chunks | ", memoryPreview.estimated_memory_items, " memory items"] }) : null] })] })] })) : ((0, jsx_runtime_1.jsx)("p", { className: "attachment-panel-empty", children: loading === "inspect" ? "Loading inspect result..." : "Select an attachment to inspect." })) })] }), (0, jsx_runtime_1.jsxs)("div", { className: "attachment-search", children: [(0, jsx_runtime_1.jsxs)("select", { value: filterId, onChange: (event) => setFilterId(event.target.value), children: [(0, jsx_runtime_1.jsx)("option", { value: "", children: "All attachments" }), attachments.map((attachment) => ((0, jsx_runtime_1.jsx)("option", { value: attachment.attachment_id, children: attachment.stored_filename }, attachment.attachment_id)))] }), (0, jsx_runtime_1.jsx)("input", { value: query, onChange: (event) => setQuery(event.target.value), placeholder: "Search attachment content" }), (0, jsx_runtime_1.jsxs)("select", { value: searchMode, onChange: (event) => setSearchMode(event.target.value), children: [(0, jsx_runtime_1.jsx)("option", { value: "auto", children: "auto" }), (0, jsx_runtime_1.jsx)("option", { value: "keyword", children: "keyword" }), (0, jsx_runtime_1.jsx)("option", { value: "hybrid", children: "hybrid" })] }), (0, jsx_runtime_1.jsx)("input", { min: 1, max: 20, type: "number", value: topK, onChange: (event) => setTopK(Number(event.target.value) || 5) }), (0, jsx_runtime_1.jsx)("button", { type: "button", onClick: searchAttachments, disabled: !query.trim() || loading === "search", children: (0, jsx_runtime_1.jsx)(lucide_react_1.Search, { size: 14 }) })] }), (0, jsx_runtime_1.jsx)("div", { className: "attachment-results", children: results.map((result) => ((0, jsx_runtime_1.jsxs)("button", { className: "attachment-result", type: "button", onClick: () => readChunk(result), children: [(0, jsx_runtime_1.jsx)("strong", { children: result.filename }), (0, jsx_runtime_1.jsxs)("span", { children: [result.source_ref || sourceLabel(result), " | score ", result.score.toFixed(1)] }), (0, jsx_runtime_1.jsx)("p", { children: result.snippet })] }, result.chunk_id))) }), chunkPreview ? ((0, jsx_runtime_1.jsxs)("div", { className: "attachment-chunk-preview", children: [(0, jsx_runtime_1.jsxs)("header", { children: [(0, jsx_runtime_1.jsxs)("div", { children: [(0, jsx_runtime_1.jsx)("strong", { children: chunkPreview.filename }), (0, jsx_runtime_1.jsxs)("span", { children: [chunkPreview.chunkId, " | ", chunkPreview.source, chunkPreview.truncated ? " | truncated" : ""] })] }), (0, jsx_runtime_1.jsx)("button", { type: "button", onClick: copyPreview, title: "Copy chunk preview", children: (0, jsx_runtime_1.jsx)(lucide_react_1.Copy, { size: 14 }) })] }), (0, jsx_runtime_1.jsx)("pre", { children: chunkPreview.text })] })) : null] }));
}
function MetadataBlock({ metadata, onSymbolClick }) {
    const outline = Array.isArray(metadata.outline) ? metadata.outline : [];
    const headings = Array.isArray(metadata.headings) ? metadata.headings : [];
    const table = typeof metadata.table === "object" && metadata.table ? metadata.table : null;
    const structure = typeof metadata.structure === "object" && metadata.structure ? metadata.structure : null;
    return ((0, jsx_runtime_1.jsxs)("div", { className: "attachment-metadata", children: [outline.length > 0 ? (0, jsx_runtime_1.jsx)(MetadataList, { title: "Symbols", items: outline.slice(0, 12), onItemClick: onSymbolClick }) : null, headings.length > 0 ? (0, jsx_runtime_1.jsx)(MetadataList, { title: "Headings", items: headings.slice(0, 12) }) : null, table ? (0, jsx_runtime_1.jsx)(MetadataJson, { title: "Table schema", value: table }) : null, structure ? (0, jsx_runtime_1.jsx)(MetadataJson, { title: "Structure", value: structure }) : null, typeof metadata.page_count === "number" ? (0, jsx_runtime_1.jsxs)("p", { children: ["Pages: ", metadata.page_count] }) : null] }));
}
function MetadataList({ title, items, onItemClick }) {
    return ((0, jsx_runtime_1.jsxs)("div", { children: [(0, jsx_runtime_1.jsx)("strong", { children: title }), (0, jsx_runtime_1.jsx)("ul", { children: items.map((item, index) => ((0, jsx_runtime_1.jsx)("li", { children: item && typeof item === "object" && onItemClick ? ((0, jsx_runtime_1.jsx)("button", { type: "button", onClick: () => onItemClick(item), children: formatMetadataItem(item) })) : (formatMetadataItem(item)) }, index))) })] }));
}
function MetadataJson({ title, value }) {
    return ((0, jsx_runtime_1.jsxs)("div", { children: [(0, jsx_runtime_1.jsx)("strong", { children: title }), (0, jsx_runtime_1.jsx)("pre", { children: JSON.stringify(value, null, 2) })] }));
}
function formatMetadataItem(item) {
    if (Array.isArray(item))
        return item.join(" > ");
    if (item && typeof item === "object") {
        const record = item;
        const name = record.name || record.kind || "item";
        const line = record.line || record.line_start;
        const end = record.end_line || record.line_end;
        return `${String(record.kind || "symbol")} ${String(name)}${line ? ` | lines ${line}${end ? `-${end}` : ""}` : ""}`;
    }
    return String(item);
}
function sourceLabel(result) {
    if (result.page_start)
        return `page ${result.page_start}${result.page_end && result.page_end !== result.page_start ? `-${result.page_end}` : ""}`;
    if (result.line_start)
        return `lines ${result.line_start}${result.line_end && result.line_end !== result.line_start ? `-${result.line_end}` : ""}`;
    return result.match_type;
}
function formatBytes(value) {
    if (!value)
        return "0 B";
    if (value < 1024)
        return `${value} B`;
    if (value < 1024 * 1024)
        return `${(value / 1024).toFixed(1)} KB`;
    return `${(value / 1024 / 1024).toFixed(1)} MB`;
}
function formatNumber(value) {
    return typeof value === "number" ? value.toLocaleString() : "0";
}
function formatDate(value) {
    if (!value)
        return "";
    return new Date(value * 1000).toLocaleDateString();
}
