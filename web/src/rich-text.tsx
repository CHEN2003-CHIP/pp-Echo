import { ReactNode, useState } from "react";
import { MessageAttachment, MessageContentPart, SnapshotMessage } from "./api";

export type RichAttachment = {
  url: string;
  alt?: string;
  title?: string;
  mimeType?: string;
  name?: string;
};

export type RichMessageBody = {
  text: string;
  attachments: RichAttachment[];
};

type MarkdownBlock =
  | { kind: "heading"; level: number; text: string }
  | { kind: "paragraph"; text: string }
  | { kind: "blockquote"; text: string }
  | { kind: "code"; language: string; text: string }
  | { kind: "list"; ordered: boolean; items: string[] }
  | { kind: "table"; header: string[]; rows: string[][] }
  | { kind: "hr" };

const INLINE_TOKEN_RE = /(!\[[^\]]*]\([^)]+\)|\[[^\]]*]\([^)]+\)|`[^`]+`|\*\*[^*]+\*\*|__[^_]+__|\*[^*]+\*|_[^_]+_)/g;
const RAW_URL_RE = /(https?:\/\/[^\s<>()]+)([)\].,!?:;]*)/gi;
const SAFE_MEDIA_PROTOCOLS = new Set(["http:", "https:", "data:", "blob:"]);
const MAX_MARKDOWN_RENDER_CHARS = 20_000;
const MAX_INLINE_MEDIA_URL_CHARS = 4096;
const MAX_MARKDOWN_PARSE_LINES = 1200;
const MAX_MARKDOWN_PARSE_BLOCKS = 800;
export const MAX_VISIBLE_ATTACHMENTS = 3;

export function extractMessageBody(message: SnapshotMessage): RichMessageBody {
  const parts = Array.isArray(message.content) ? message.content : [];
  const textParts: string[] = [];
  const attachments: RichAttachment[] = [];
  const seen = new Set<string>();

  for (const part of parts) {
    if (isTextPart(part)) {
      textParts.push(part.text);
      continue;
    }
    if (isImagePart(part)) {
      pushAttachment(
        attachments,
        seen,
        normalizeAttachment({
          url: part.url,
          alt: part.alt,
          title: part.title,
          mimeType: part.mime_type,
        }),
      );
    }
  }

  const metadata = message.metadata as Record<string, unknown> | undefined;
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

export function RichMarkdown({ text, className = "", streaming = false, plain = false }: { text: string; className?: string; streaming?: boolean; plain?: boolean }) {
  if (streaming) {
    return (
      <p className={className ? `md-paragraph md-streaming-plain ${className}` : "md-paragraph md-streaming-plain"}>
        {text}
        <span className="stream-cursor markdown-cursor" />
      </p>
    );
  }
  if (!text) {
    return null;
  }
  return <pre className={className ? `markdown md-large-plain ${className}` : "markdown md-large-plain"}>{text}</pre>;
}

export function RichMessageAttachments({ attachments }: { attachments: RichAttachment[] }) {
  if (!attachments.length) return null;
  const { visible, hiddenCount } = partitionVisibleAttachments(attachments);
  return (
    <div className="attachment-grid">
      {visible.map((attachment, index) => {
        const label = attachment.alt || attachment.title || attachment.name || `Image ${index + 1}`;
        return (
          <figure className="attachment-card" key={`${attachment.url}-${index}`}>
            <a href={attachment.url} target="_blank" rel="noreferrer noopener" title={label}>
              <img src={attachment.url} alt={attachment.alt || label} loading="lazy" />
            </a>
            <figcaption>
              <span>{label}</span>
              {attachment.title && attachment.title !== label && <small>{attachment.title}</small>}
            </figcaption>
          </figure>
        );
      })}
      {hiddenCount > 0 ? (
        <div className="attachment-card attachment-overflow">
          <span>{hiddenCount} more attachment{hiddenCount === 1 ? "" : "s"}</span>
        </div>
      ) : null}
    </div>
  );
}

export function partitionVisibleAttachments(attachments: RichAttachment[], limit = MAX_VISIBLE_ATTACHMENTS) {
  const safeLimit = Math.max(0, limit);
  return {
    visible: attachments.slice(0, safeLimit),
    hiddenCount: Math.max(0, attachments.length - safeLimit),
  };
}

export function RichMessageContent({ text, attachments, streaming = false, plain = false }: { text: string; attachments: RichAttachment[]; streaming?: boolean; plain?: boolean }) {
  return (
    <div className="message-body">
      <RichMarkdown text={text} streaming={streaming} plain={plain} />
      {!streaming && <RichMessageAttachments attachments={attachments} />}
    </div>
  );
}

function renderBlock(block: MarkdownBlock, index: number): ReactNode {
  switch (block.kind) {
    case "heading":
      return (
        <div className={`md-heading md-h${block.level}`} key={`heading-${index}`}>
          {renderInline(block.text)}
        </div>
      );
    case "paragraph":
      return (
        <p className="md-paragraph" key={`paragraph-${index}`}>
          {renderInline(block.text)}
        </p>
      );
    case "blockquote":
      return (
        <blockquote className="md-blockquote" key={`blockquote-${index}`}>
          <RichMarkdown text={block.text} />
        </blockquote>
      );
    case "code":
      return (
        <pre className="md-code-block" key={`code-${index}`}>
          {block.language ? <div className="md-code-language">{block.language}</div> : null}
          <code>{block.text}</code>
        </pre>
      );
    case "list":
      return block.ordered ? (
        <ol className="md-list" key={`list-${index}`}>
          {block.items.map((item, itemIndex) => (
            <li key={`ordered-${index}-${itemIndex}`}>{renderInline(item)}</li>
          ))}
        </ol>
      ) : (
        <ul className="md-list" key={`list-${index}`}>
          {block.items.map((item, itemIndex) => (
            <li key={`unordered-${index}-${itemIndex}`}>{renderInline(item)}</li>
          ))}
        </ul>
      );
    case "table":
      return (
        <div className="md-table-wrap" key={`table-${index}`}>
          <table className="md-table">
            <thead>
              <tr>
                {block.header.map((cell, cellIndex) => (
                  <th key={`table-h-${index}-${cellIndex}`}>{renderInline(cell)}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {block.rows.map((row, rowIndex) => (
                <tr key={`table-r-${index}-${rowIndex}`}>
                  {block.header.map((_, cellIndex) => (
                    <td key={`table-c-${index}-${rowIndex}-${cellIndex}`}>{renderInline(row[cellIndex] || "")}</td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      );
    case "hr":
      return <hr className="md-hr" key={`hr-${index}`} />;
    default:
      return null;
  }
}

function renderInline(text: string): ReactNode[] {
  const nodes: ReactNode[] = [];
  let cursor = 0;
  let match: RegExpExecArray | null;

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

function appendText(nodes: ReactNode[], text: string) {
  if (!text) return;
  const chunks = text.split(/\n/);
  chunks.forEach((chunk, index) => {
    if (chunk) {
      appendUrlifiedText(nodes, chunk);
    }
    if (index < chunks.length - 1) {
      nodes.push(<br key={`br-${nodes.length}-${index}`} />);
    }
  });
}

function appendUrlifiedText(nodes: ReactNode[], text: string) {
  let cursor = 0;
  let match: RegExpExecArray | null;
  RAW_URL_RE.lastIndex = 0;
  while ((match = RAW_URL_RE.exec(text)) !== null) {
    const before = text.slice(cursor, match.index);
    if (before) nodes.push(before);
    const href = match[1];
    const tail = match[2] || "";
    nodes.push(
      <a key={`url-${nodes.length}-${match.index}`} href={href} target="_blank" rel="noreferrer noopener">
        {href}
      </a>,
    );
    if (tail) nodes.push(tail);
    cursor = match.index + match[0].length;
  }
  const remaining = text.slice(cursor);
  if (remaining) nodes.push(remaining);
}

function renderToken(token: string, keySeed: number): ReactNode {
  if (token.startsWith("![") && token.includes("](")) {
    const image = parseMarkdownLink(token);
    if (image) {
      const safe = sanitizeMediaUrl(image.url, { allowRelative: true });
      if (safe) {
        return <MarkdownImage key={`img-${keySeed}`} url={safe} alt={image.label} title={image.title} />;
      }
    }
    return token;
  }
  if (token.startsWith("[") && token.includes("](")) {
    const link = parseMarkdownLink(token);
    if (link) {
      const safe = sanitizeMediaUrl(link.url, { allowRelative: true });
      if (safe) {
        return (
          <a key={`link-${keySeed}`} href={safe} target="_blank" rel="noreferrer noopener">
            {renderInline(link.label)}
          </a>
        );
      }
    }
    return token;
  }
  if (token.startsWith("`") && token.endsWith("`")) {
    return (
      <code className="md-inline-code" key={`code-${keySeed}`}>
        {token.slice(1, -1)}
      </code>
    );
  }
  if ((token.startsWith("**") && token.endsWith("**")) || (token.startsWith("__") && token.endsWith("__"))) {
    return <strong key={`strong-${keySeed}`}>{renderInline(token.slice(2, -2))}</strong>;
  }
  if ((token.startsWith("*") && token.endsWith("*")) || (token.startsWith("_") && token.endsWith("_"))) {
    return <em key={`em-${keySeed}`}>{renderInline(token.slice(1, -1))}</em>;
  }
  return token;
}

function parseMarkdownLink(token: string): { label: string; url: string; title?: string } | null {
  const start = token.indexOf("[");
  const mid = token.indexOf("](");
  const end = token.lastIndexOf(")");
  if (start !== 0 || mid < 0 || end <= mid + 2) return null;
  const label = token.slice(1, mid);
  const rawTarget = token.slice(mid + 2, end);
  const { url, title } = splitMarkdownTarget(rawTarget);
  return { label, url, title };
}

function splitMarkdownTarget(target: string): { url: string; title?: string } {
  const trimmed = target.trim();
  const quoted = trimmed.match(/^(.*)\s+"([^"]+)"$/);
  if (quoted) {
    return { url: quoted[1].trim(), title: quoted[2] };
  }
  return { url: trimmed };
}

export function parseMarkdown(text: string): MarkdownBlock[] {
  const normalized = text.replace(/\r\n/g, "\n");
  const lines = normalized.split("\n");
  if (lines.length > MAX_MARKDOWN_PARSE_LINES) {
    return [{ kind: "code", language: "", text }];
  }
  const blocks: MarkdownBlock[] = [];
  let index = 0;
  let guard = 0;

  while (index < lines.length && blocks.length < MAX_MARKDOWN_PARSE_BLOCKS && guard < lines.length * 4 + 20) {
    guard += 1;
    const startIndex = index;
    const line = lines[index];
    if (!line.trim()) {
      index += 1;
      continue;
    }

    const fence = line.match(/^```(\w+)?\s*$/);
    if (fence) {
      const language = fence[1] || "";
      index += 1;
      const body: string[] = [];
      while (index < lines.length && !/^```\s*$/.test(lines[index])) {
        body.push(lines[index]);
        index += 1;
      }
      if (index < lines.length) index += 1;
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
      const quoteLines: string[] = [];
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
      index = table.nextIndex > index ? table.nextIndex : index + 1;
      continue;
    }

    const list = tryParseList(lines, index);
    if (list) {
      blocks.push(list.block);
      index = list.nextIndex > index ? list.nextIndex : index + 1;
      continue;
    }

    const paragraphLines: string[] = [];
    while (index < lines.length) {
      const current = lines[index];
      if (!current.trim()) break;
      if (isBlockBoundary(current) && paragraphLines.length > 0) break;
      paragraphLines.push(current.trim());
      index += 1;
    }
    blocks.push({ kind: "paragraph", text: paragraphLines.join(" ") });
    if (index === startIndex) {
      index += 1;
    }
  }

  if (index < lines.length) {
    blocks.push({ kind: "code", language: "", text: lines.slice(index).join("\n") });
  }

  return blocks;
}

function safeParseMarkdown(text: string): MarkdownBlock[] {
  try {
    return parseMarkdown(text);
  } catch {
    return [{ kind: "code", language: "", text }];
  }
}

function isBlockBoundary(line: string) {
  return (
    /^```/.test(line) ||
    /^(#{1,6})\s+/.test(line) ||
    /^\s*>/.test(line) ||
    /^(\s*)([-*+])\s+/.test(line) ||
    /^(\s*)\d+\.\s+/.test(line) ||
    /^(-{3,}|\*{3,}|_{3,})\s*$/.test(line.trim())
  );
}

function tryParseList(lines: string[], startIndex: number): { block: MarkdownBlock; nextIndex: number } | null {
  const first = lines[startIndex].match(/^(\s*)([-*+])\s+(.*)$/) || lines[startIndex].match(/^(\s*)\d+\.\s+(.*)$/);
  if (!first) return null;
  const ordered = /^\s*\d+\.\s+/.test(lines[startIndex]);
  const items: string[] = [];
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
      if (index < lines.length && !lines[index].trim()) break;
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

function tryParseTable(lines: string[], startIndex: number): { block: MarkdownBlock; nextIndex: number } | null {
  const headerLine = lines[startIndex];
  const separatorLine = lines[startIndex + 1];
  if (!headerLine.includes("|") || !separatorLine) return null;
  if (!/^\s*\|?(?:\s*:?-{3,}:?\s*\|)+\s*$/.test(separatorLine)) return null;
  const header = splitTableRow(headerLine);
  const rows: string[][] = [];
  let index = startIndex + 2;
  while (index < lines.length && lines[index].includes("|") && lines[index].trim()) {
    rows.push(splitTableRow(lines[index]));
    index += 1;
  }
  return { block: { kind: "table", header, rows }, nextIndex: index };
}

function splitTableRow(line: string): string[] {
  return line
    .trim()
    .replace(/^\|/, "")
    .replace(/\|$/, "")
    .split("|")
    .map((cell) => cell.trim());
}

function isTextPart(part: MessageContentPart): part is { type: "text"; text: string } {
  return typeof part === "object" && part !== null && part.type === "text" && typeof part.text === "string";
}

function isImagePart(part: MessageContentPart): part is { type: "image"; url: string; alt?: string; title?: string; mime_type?: string } {
  return typeof part === "object" && part !== null && part.type === "image" && typeof part.url === "string";
}

function normalizeAttachment(value: unknown): RichAttachment | null {
  if (typeof value === "string") {
    const url = sanitizeMediaUrl(value, { allowRelative: true });
    return url ? { url } : null;
  }
  if (!value || typeof value !== "object") return null;
  const data = value as Record<string, unknown>;
  const urlCandidate = firstString(data.url, data.src, data.href, data.image_url);
  if (!urlCandidate) return null;
  const url = sanitizeMediaUrl(urlCandidate, { allowRelative: true });
  if (!url) return null;
  return {
    url,
    alt: firstString(data.alt, data.caption, data.description),
    title: firstString(data.title, data.name),
    mimeType: firstString(data.mime_type, data.mimeType),
    name: firstString(data.name, data.filename),
  };
}

function pushAttachment(target: RichAttachment[], seen: Set<string>, attachment: RichAttachment | null) {
  if (!attachment) return;
  const key = `${attachment.url}::${attachment.alt || ""}::${attachment.title || ""}`;
  if (seen.has(key)) return;
  seen.add(key);
  target.push(attachment);
}

function firstString(...values: unknown[]): string | undefined {
  for (const value of values) {
    if (typeof value === "string" && value.trim()) return value.trim();
  }
  return undefined;
}

export function sanitizeMediaUrl(raw: string, options: { allowRelative: boolean }): string | null {
  const value = raw.trim();
  if (!value) return null;
  if (/^(data:|blob:)/i.test(value) && value.length > MAX_INLINE_MEDIA_URL_CHARS) return null;
  if (/^javascript:/i.test(value) || /^file:/i.test(value)) return null;
  try {
    const baseHref = typeof window !== "undefined" && window.location?.href ? window.location.href : "http://localhost/";
    const baseOrigin = typeof window !== "undefined" && window.location?.origin ? window.location.origin : "http://localhost";
    const parsed = new URL(value, baseHref);
    if (!SAFE_MEDIA_PROTOCOLS.has(parsed.protocol)) return null;
    if (!options.allowRelative && !/^([a-z]+:)?\/\//i.test(value) && parsed.origin !== baseOrigin) {
      return null;
    }
    return parsed.toString();
  } catch {
    if (/^(https?:|data:|blob:)/i.test(value)) return value;
    return null;
  }
}

function MarkdownImage({ url, alt, title }: { url: string; alt?: string; title?: string }) {
  const [broken, setBroken] = useState(false);
  const label = alt || title || "Image";
  if (broken) {
    return (
      <div className="md-image-fallback">
        <span>{label}</span>
        <small>{url}</small>
      </div>
    );
  }
  return (
    <figure className="md-image">
      <a href={url} target="_blank" rel="noreferrer noopener" title={label}>
        <img src={url} alt={alt || label} loading="lazy" onError={() => setBroken(true)} />
      </a>
      {title || alt ? <figcaption>{title || alt}</figcaption> : null}
    </figure>
  );
}
