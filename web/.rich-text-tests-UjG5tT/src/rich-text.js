"use strict";
Object.defineProperty(exports, "__esModule", { value: true });
exports.extractMessageBody = extractMessageBody;
exports.RichMarkdown = RichMarkdown;
exports.RichMessageAttachments = RichMessageAttachments;
exports.RichMessageContent = RichMessageContent;
exports.parseMarkdown = parseMarkdown;
const jsx_runtime_1 = require("react/jsx-runtime");
const react_1 = require("react");
const INLINE_TOKEN_RE = /(!\[[^\]]*]\([^)]+\)|\[[^\]]*]\([^)]+\)|`[^`]+`|\*\*[^*]+\*\*|__[^_]+__|\*[^*]+\*|_[^_]+_)/g;
const RAW_URL_RE = /(https?:\/\/[^\s<>()]+)([)\].,!?:;]*)/gi;
const SAFE_MEDIA_PROTOCOLS = new Set(["http:", "https:", "data:", "blob:"]);
function extractMessageBody(message) {
    const parts = Array.isArray(message.content) ? message.content : [];
    const textParts = [];
    const attachments = [];
    const seen = new Set();
    for (const part of parts) {
        if (isTextPart(part)) {
            textParts.push(part.text);
            continue;
        }
        if (isImagePart(part)) {
            pushAttachment(attachments, seen, normalizeAttachment({
                url: part.url,
                alt: part.alt,
                title: part.title,
                mimeType: part.mime_type,
            }));
        }
    }
    const metadata = message.metadata;
    if (metadata) {
        const imageSources = [
            ...(Array.isArray(metadata.attachments) ? metadata.attachments : []),
            ...(Array.isArray(metadata.images) ? metadata.images : []),
        ];
        for (const source of imageSources) {
            pushAttachment(attachments, seen, normalizeAttachment(source));
        }
    }
    return {
        text: textParts.join("\n"),
        attachments,
    };
}
function RichMarkdown({ text, className = "", streaming = false }) {
    const blocks = (0, react_1.useMemo)(() => parseMarkdown(text), [text]);
    if (blocks.length === 0) {
        return streaming ? (0, jsx_runtime_1.jsx)("span", { className: "stream-cursor markdown-cursor" }) : null;
    }
    return ((0, jsx_runtime_1.jsxs)("div", { className: className ? `markdown ${className}` : "markdown", children: [blocks.map((block, index) => renderBlock(block, index)), streaming && (0, jsx_runtime_1.jsx)("span", { className: "stream-cursor markdown-cursor" })] }));
}
function RichMessageAttachments({ attachments }) {
    if (!attachments.length)
        return null;
    return ((0, jsx_runtime_1.jsx)("div", { className: "attachment-grid", children: attachments.map((attachment, index) => {
            const label = attachment.alt || attachment.title || attachment.name || `Image ${index + 1}`;
            return ((0, jsx_runtime_1.jsxs)("figure", { className: "attachment-card", children: [(0, jsx_runtime_1.jsx)("a", { href: attachment.url, target: "_blank", rel: "noreferrer noopener", title: label, children: (0, jsx_runtime_1.jsx)("img", { src: attachment.url, alt: attachment.alt || label, loading: "lazy" }) }), (0, jsx_runtime_1.jsxs)("figcaption", { children: [(0, jsx_runtime_1.jsx)("span", { children: label }), attachment.title && attachment.title !== label && (0, jsx_runtime_1.jsx)("small", { children: attachment.title })] })] }, `${attachment.url}-${index}`));
        }) }));
}
function RichMessageContent({ text, attachments, streaming = false }) {
    return ((0, jsx_runtime_1.jsxs)("div", { className: "message-body", children: [(0, jsx_runtime_1.jsx)(RichMarkdown, { text: text, streaming: streaming }), (0, jsx_runtime_1.jsx)(RichMessageAttachments, { attachments: attachments })] }));
}
function renderBlock(block, index) {
    switch (block.kind) {
        case "heading":
            return ((0, jsx_runtime_1.jsx)("div", { className: `md-heading md-h${block.level}`, children: renderInline(block.text) }, `heading-${index}`));
        case "paragraph":
            return ((0, jsx_runtime_1.jsx)("p", { className: "md-paragraph", children: renderInline(block.text) }, `paragraph-${index}`));
        case "blockquote":
            return ((0, jsx_runtime_1.jsx)("blockquote", { className: "md-blockquote", children: (0, jsx_runtime_1.jsx)(RichMarkdown, { text: block.text }) }, `blockquote-${index}`));
        case "code":
            return ((0, jsx_runtime_1.jsxs)("pre", { className: "md-code-block", children: [block.language ? (0, jsx_runtime_1.jsx)("div", { className: "md-code-language", children: block.language }) : null, (0, jsx_runtime_1.jsx)("code", { children: block.text })] }, `code-${index}`));
        case "list":
            return block.ordered ? ((0, jsx_runtime_1.jsx)("ol", { className: "md-list", children: block.items.map((item, itemIndex) => ((0, jsx_runtime_1.jsx)("li", { children: renderInline(item) }, `ordered-${index}-${itemIndex}`))) }, `list-${index}`)) : ((0, jsx_runtime_1.jsx)("ul", { className: "md-list", children: block.items.map((item, itemIndex) => ((0, jsx_runtime_1.jsx)("li", { children: renderInline(item) }, `unordered-${index}-${itemIndex}`))) }, `list-${index}`));
        case "table":
            return ((0, jsx_runtime_1.jsx)("div", { className: "md-table-wrap", children: (0, jsx_runtime_1.jsxs)("table", { className: "md-table", children: [(0, jsx_runtime_1.jsx)("thead", { children: (0, jsx_runtime_1.jsx)("tr", { children: block.header.map((cell, cellIndex) => ((0, jsx_runtime_1.jsx)("th", { children: renderInline(cell) }, `table-h-${index}-${cellIndex}`))) }) }), (0, jsx_runtime_1.jsx)("tbody", { children: block.rows.map((row, rowIndex) => ((0, jsx_runtime_1.jsx)("tr", { children: block.header.map((_, cellIndex) => ((0, jsx_runtime_1.jsx)("td", { children: renderInline(row[cellIndex] || "") }, `table-c-${index}-${rowIndex}-${cellIndex}`))) }, `table-r-${index}-${rowIndex}`))) })] }) }, `table-${index}`));
        case "hr":
            return (0, jsx_runtime_1.jsx)("hr", { className: "md-hr" }, `hr-${index}`);
        default:
            return null;
    }
}
function renderInline(text) {
    const nodes = [];
    let cursor = 0;
    let match;
    INLINE_TOKEN_RE.lastIndex = 0;
    while ((match = INLINE_TOKEN_RE.exec(text)) !== null) {
        const before = text.slice(cursor, match.index);
        appendText(nodes, before);
        nodes.push(renderToken(match[0], nodes.length));
        cursor = match.index + match[0].length;
    }
    appendText(nodes, text.slice(cursor));
    return nodes;
}
function appendText(nodes, text) {
    if (!text)
        return;
    const chunks = text.split(/\n/);
    chunks.forEach((chunk, index) => {
        if (chunk) {
            appendUrlifiedText(nodes, chunk);
        }
        if (index < chunks.length - 1) {
            nodes.push((0, jsx_runtime_1.jsx)("br", {}, `br-${nodes.length}-${index}`));
        }
    });
}
function appendUrlifiedText(nodes, text) {
    let cursor = 0;
    let match;
    RAW_URL_RE.lastIndex = 0;
    while ((match = RAW_URL_RE.exec(text)) !== null) {
        const before = text.slice(cursor, match.index);
        if (before)
            nodes.push(before);
        const href = match[1];
        const tail = match[2] || "";
        nodes.push((0, jsx_runtime_1.jsx)("a", { href: href, target: "_blank", rel: "noreferrer noopener", children: href }, `url-${nodes.length}-${match.index}`));
        if (tail)
            nodes.push(tail);
        cursor = match.index + match[0].length;
    }
    const remaining = text.slice(cursor);
    if (remaining)
        nodes.push(remaining);
}
function renderToken(token, keySeed) {
    if (token.startsWith("![") && token.includes("](")) {
        const image = parseMarkdownLink(token);
        if (image) {
            const safe = sanitizeMediaUrl(image.url, { allowRelative: true });
            if (safe) {
                return (0, jsx_runtime_1.jsx)(MarkdownImage, { url: safe, alt: image.label, title: image.title }, `img-${keySeed}`);
            }
        }
        return token;
    }
    if (token.startsWith("[") && token.includes("](")) {
        const link = parseMarkdownLink(token);
        if (link) {
            const safe = sanitizeMediaUrl(link.url, { allowRelative: true });
            if (safe) {
                return ((0, jsx_runtime_1.jsx)("a", { href: safe, target: "_blank", rel: "noreferrer noopener", children: renderInline(link.label) }, `link-${keySeed}`));
            }
        }
        return token;
    }
    if (token.startsWith("`") && token.endsWith("`")) {
        return ((0, jsx_runtime_1.jsx)("code", { className: "md-inline-code", children: token.slice(1, -1) }, `code-${keySeed}`));
    }
    if ((token.startsWith("**") && token.endsWith("**")) || (token.startsWith("__") && token.endsWith("__"))) {
        return (0, jsx_runtime_1.jsx)("strong", { children: renderInline(token.slice(2, -2)) }, `strong-${keySeed}`);
    }
    if ((token.startsWith("*") && token.endsWith("*")) || (token.startsWith("_") && token.endsWith("_"))) {
        return (0, jsx_runtime_1.jsx)("em", { children: renderInline(token.slice(1, -1)) }, `em-${keySeed}`);
    }
    return token;
}
function parseMarkdownLink(token) {
    const start = token.indexOf("[");
    const mid = token.indexOf("](");
    const end = token.lastIndexOf(")");
    if (start !== 0 || mid < 0 || end <= mid + 2)
        return null;
    const label = token.slice(1, mid);
    const rawTarget = token.slice(mid + 2, end);
    const { url, title } = splitMarkdownTarget(rawTarget);
    return { label, url, title };
}
function splitMarkdownTarget(target) {
    const trimmed = target.trim();
    const quoted = trimmed.match(/^(.*)\s+"([^"]+)"$/);
    if (quoted) {
        return { url: quoted[1].trim(), title: quoted[2] };
    }
    return { url: trimmed };
}
function parseMarkdown(text) {
    const normalized = text.replace(/\r\n/g, "\n");
    const lines = normalized.split("\n");
    const blocks = [];
    let index = 0;
    while (index < lines.length) {
        const line = lines[index];
        if (!line.trim()) {
            index += 1;
            continue;
        }
        const fence = line.match(/^```(\w+)?\s*$/);
        if (fence) {
            const language = fence[1] || "";
            index += 1;
            const body = [];
            while (index < lines.length && !/^```\s*$/.test(lines[index])) {
                body.push(lines[index]);
                index += 1;
            }
            if (index < lines.length)
                index += 1;
            blocks.push({ kind: "code", language, text: body.join("\n") });
            continue;
        }
        const heading = line.match(/^(#{1,6})\s+(.*)$/);
        if (heading) {
            blocks.push({ kind: "heading", level: heading[1].length, text: heading[2].trim() });
            index += 1;
            continue;
        }
        if (/^(-{3,}|\*{3,}|_{3,})\s*$/.test(line.trim())) {
            blocks.push({ kind: "hr" });
            index += 1;
            continue;
        }
        if (/^\s*>/.test(line)) {
            const quoteLines = [];
            while (index < lines.length && (/^\s*>/.test(lines[index]) || !lines[index].trim())) {
                quoteLines.push(lines[index].replace(/^\s*>\s?/, ""));
                index += 1;
            }
            blocks.push({ kind: "blockquote", text: quoteLines.join("\n").trim() });
            continue;
        }
        const table = tryParseTable(lines, index);
        if (table) {
            blocks.push(table.block);
            index = table.nextIndex;
            continue;
        }
        const list = tryParseList(lines, index);
        if (list) {
            blocks.push(list.block);
            index = list.nextIndex;
            continue;
        }
        const paragraphLines = [];
        while (index < lines.length) {
            const current = lines[index];
            if (!current.trim())
                break;
            if (isBlockBoundary(current))
                break;
            paragraphLines.push(current.trim());
            index += 1;
        }
        blocks.push({ kind: "paragraph", text: paragraphLines.join(" ") });
    }
    return blocks;
}
function isBlockBoundary(line) {
    return (/^```/.test(line) ||
        /^(#{1,6})\s+/.test(line) ||
        /^\s*>/.test(line) ||
        /^(\s*)([-*+])\s+/.test(line) ||
        /^(\s*)\d+\.\s+/.test(line) ||
        /^(-{3,}|\*{3,}|_{3,})\s*$/.test(line.trim()));
}
function tryParseList(lines, startIndex) {
    const first = lines[startIndex].match(/^(\s*)([-*+])\s+(.*)$/) || lines[startIndex].match(/^(\s*)\d+\.\s+(.*)$/);
    if (!first)
        return null;
    const ordered = /^\s*\d+\.\s+/.test(lines[startIndex]);
    const items = [];
    let index = startIndex;
    while (index < lines.length) {
        const line = lines[index];
        const itemMatch = ordered
            ? line.match(/^(\s*)\d+\.\s+(.*)$/)
            : line.match(/^(\s*)([-*+])\s+(.*)$/);
        if (itemMatch) {
            items.push(itemMatch[itemMatch.length - 1].trim());
            index += 1;
            continue;
        }
        if (!line.trim()) {
            index += 1;
            if (index < lines.length && !lines[index].trim())
                break;
            continue;
        }
        if (/^\s{2,}\S/.test(line)) {
            items[items.length - 1] = `${items[items.length - 1]}\n${line.trim()}`;
            index += 1;
            continue;
        }
        break;
    }
    return { block: { kind: "list", ordered, items }, nextIndex: index };
}
function tryParseTable(lines, startIndex) {
    const headerLine = lines[startIndex];
    const separatorLine = lines[startIndex + 1];
    if (!headerLine.includes("|") || !separatorLine)
        return null;
    if (!/^\s*\|?(?:\s*:?-{3,}:?\s*\|)+\s*$/.test(separatorLine))
        return null;
    const header = splitTableRow(headerLine);
    const rows = [];
    let index = startIndex + 2;
    while (index < lines.length && lines[index].includes("|") && lines[index].trim()) {
        rows.push(splitTableRow(lines[index]));
        index += 1;
    }
    return { block: { kind: "table", header, rows }, nextIndex: index };
}
function splitTableRow(line) {
    return line
        .trim()
        .replace(/^\|/, "")
        .replace(/\|$/, "")
        .split("|")
        .map((cell) => cell.trim());
}
function isTextPart(part) {
    return typeof part === "object" && part !== null && part.type === "text" && typeof part.text === "string";
}
function isImagePart(part) {
    return typeof part === "object" && part !== null && part.type === "image" && typeof part.url === "string";
}
function normalizeAttachment(value) {
    if (typeof value === "string") {
        const url = sanitizeMediaUrl(value, { allowRelative: true });
        return url ? { url } : null;
    }
    if (!value || typeof value !== "object")
        return null;
    const data = value;
    const urlCandidate = firstString(data.url, data.src, data.href, data.image_url);
    if (!urlCandidate)
        return null;
    const url = sanitizeMediaUrl(urlCandidate, { allowRelative: true });
    if (!url)
        return null;
    return {
        url,
        alt: firstString(data.alt, data.caption, data.description),
        title: firstString(data.title, data.name),
        mimeType: firstString(data.mime_type, data.mimeType),
        name: firstString(data.name, data.filename),
    };
}
function pushAttachment(target, seen, attachment) {
    if (!attachment)
        return;
    const key = `${attachment.url}::${attachment.alt || ""}::${attachment.title || ""}`;
    if (seen.has(key))
        return;
    seen.add(key);
    target.push(attachment);
}
function firstString(...values) {
    for (const value of values) {
        if (typeof value === "string" && value.trim())
            return value.trim();
    }
    return undefined;
}
function sanitizeMediaUrl(raw, options) {
    const value = raw.trim();
    if (!value)
        return null;
    if (/^javascript:/i.test(value) || /^file:/i.test(value))
        return null;
    try {
        const baseHref = typeof window !== "undefined" && window.location?.href ? window.location.href : "http://localhost/";
        const baseOrigin = typeof window !== "undefined" && window.location?.origin ? window.location.origin : "http://localhost";
        const parsed = new URL(value, baseHref);
        if (!SAFE_MEDIA_PROTOCOLS.has(parsed.protocol))
            return null;
        if (!options.allowRelative && !/^([a-z]+:)?\/\//i.test(value) && parsed.origin !== baseOrigin) {
            return null;
        }
        return parsed.toString();
    }
    catch {
        if (/^(https?:|data:|blob:)/i.test(value))
            return value;
        return null;
    }
}
function MarkdownImage({ url, alt, title }) {
    const [broken, setBroken] = (0, react_1.useState)(false);
    const label = alt || title || "Image";
    if (broken) {
        return ((0, jsx_runtime_1.jsxs)("div", { className: "md-image-fallback", children: [(0, jsx_runtime_1.jsx)("span", { children: label }), (0, jsx_runtime_1.jsx)("small", { children: url })] }));
    }
    return ((0, jsx_runtime_1.jsxs)("figure", { className: "md-image", children: [(0, jsx_runtime_1.jsx)("a", { href: url, target: "_blank", rel: "noreferrer noopener", title: label, children: (0, jsx_runtime_1.jsx)("img", { src: url, alt: alt || label, loading: "lazy", onError: () => setBroken(true) }) }), title || alt ? (0, jsx_runtime_1.jsx)("figcaption", { children: title || alt }) : null] }));
}
