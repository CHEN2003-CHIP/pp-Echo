import type { TraceDetail, TraceRunSummary, TraceSpan } from "../../api";
import { formatDuration, safeJsonStringify } from "./trace-utils";

export type ContextSourceRow = {
  source: string;
  section: string;
  chars: number | null;
  tokens: number | null;
  reason: string;
  preview: string;
  raw: Record<string, unknown>;
};

export type ContextSection = {
  name: string;
  title: string;
  text: string;
  chars: number;
  tokens: number | null;
  sources: number | null;
};

export type ContextReportView = {
  totalBudget: number | null;
  used: number | null;
  sections: Array<{
    name: string;
    budget: number | null;
    used: number | null;
    included: number | null;
    dropped: number | null;
  }>;
  modelInputSections: ContextSection[];
  modelInputCaptureMode: "captured" | "preview" | "reconstructed" | "missing";
  includedSources: ContextSourceRow[];
  droppedSources: ContextSourceRow[];
  fallbackReason?: string;
  warnings: string[];
};

export function metricValue(value: unknown, fallback = "Not captured") {
  if (value === null || value === undefined || value === "") return fallback;
  if (typeof value === "number") return Number.isFinite(value) ? value.toLocaleString() : fallback;
  return String(value);
}

export function textValue(value: unknown, fallback = "Not captured") {
  if (value === null || value === undefined || value === "") return fallback;
  return String(value);
}

export function summaryFromDetail(detail: TraceDetail | null, fallbackRun?: TraceRunSummary | null) {
  return detail?.summary || fallbackRun || null;
}

export function timelineMaxDuration(spans: TraceSpan[]) {
  return Math.max(1, ...spans.map((span) => span.duration_ms || 0));
}

export function spanSubtitle(span: TraceSpan) {
  return textValue(span.attributes?.label || span.attributes?.model || span.attributes?.tool_name || span.span_type, span.span_type);
}

export function traceRisk(summary?: TraceRunSummary | null) {
  return summary?.risk_level || "low";
}

export function traceErrorCount(summary?: TraceRunSummary | null) {
  if (!summary) return 0;
  return (summary.error_count || 0) + (summary.tool_error_count || 0);
}

export function findContextReport(detail: TraceDetail): ContextReportView {
  const candidates: Record<string, unknown>[] = [];

  for (const event of detail.events || []) {
    candidates.push(event.payload, event.attributes);
    const details = objectValue(event.payload?.details) || objectValue(event.attributes?.details);
    if (details) candidates.push(details);
  }

  for (const span of detail.spans || []) {
    candidates.push(span.output, span.input, span.attributes);
    const context = objectValue(span.output?.context) || objectValue(span.input?.context) || objectValue(span.attributes?.context);
    if (context) candidates.push(context);
  }

  if (detail.run) candidates.push(detail.run);

  const found = candidates
    .map((candidate) => pickContextPayload(candidate))
    .find((candidate): candidate is Record<string, unknown> => Boolean(candidate));

  return normalizeContextReport(found || {});
}

export function safeRawTrace(detail: TraceDetail) {
  return sanitizePrivateReasoning(detail);
}

export function rawJson(detail: TraceDetail) {
  return safeJsonStringify(safeRawTrace(detail));
}

export function shortJson(value: unknown) {
  const text = safeJsonStringify(sanitizePrivateReasoning(value));
  return text.length > 1200 ? `${text.slice(0, 1200)}\n...` : text;
}

export function statusCopy(status?: string | null) {
  if (!status) return "Not captured";
  const labels: Record<string, string> = {
    ok: "Success",
    error: "Error",
    blocked: "Blocked",
    pending: "Pending",
    running: "Running",
    cancelled: "Cancelled"
  };
  return labels[status] || status;
}

export function modelSummary(summary?: TraceRunSummary | null) {
  if (!summary) return "Not captured";
  return [summary.provider, summary.model].filter(Boolean).join(" / ") || "Not captured";
}

export function tokenTotal(summary?: TraceRunSummary | null) {
  return (summary?.total_input_tokens || 0) + (summary?.total_output_tokens || 0);
}

export function runDuration(summary?: TraceRunSummary | null) {
  return formatDuration(summary?.duration_ms);
}

function pickContextPayload(value: Record<string, unknown> | null | undefined): Record<string, unknown> | null {
  if (!value) return null;
  const directKeys = ["context_report", "budget_report", "report"];
  for (const key of directKeys) {
    const nested = objectValue(value[key]);
    if (looksLikeContext(nested)) return nested;
  }
  const contextPack = objectValue(value.context_pack);
  const contextPackReport = objectValue(contextPack?.report);
  if (looksLikeContext(contextPackReport)) return contextPackReport;
  const context = objectValue(value.context);
  const budget = objectValue(context?.budget_report);
  if (looksLikeContext(budget)) {
    return {
      ...budget,
      model_input: context?.model_input,
      model_input_preview: context?.model_input_preview,
      model_input_sections: context?.model_input_sections,
      included_sources: context?.included_sources,
      dropped_sources: context?.dropped_sources
    };
  }
  if (looksLikeContext(value)) return value;
  return null;
}

function looksLikeContext(value: Record<string, unknown> | null | undefined) {
  if (!value) return false;
  return Boolean(
    value.total_budget ||
    value.per_section ||
    value.included_items ||
    value.dropped_items ||
    value.included_sources ||
    value.dropped_sources ||
    value.model_input ||
    value.model_input_preview ||
    value.model_input_sections ||
    value.sections
  );
}

function normalizeContextReport(raw: Record<string, unknown>): ContextReportView {
  const perSection = objectValue(raw.per_section) || objectValue(raw.sections) || {};
  const totalBudget = numberValue(raw.total_budget ?? raw.budget ?? raw.max_tokens);
  const used = numberValue(raw.used ?? raw.used_tokens ?? raw.used_chars ?? raw.total_used);
  const sectionRows = Object.entries(perSection).map(([name, value]) => {
    const row = objectValue(value) || {};
    return {
      name,
      budget: numberValue(row.budget ?? row.max ?? row.max_tokens),
      used: numberValue(row.used ?? row.tokens ?? row.chars),
      included: numberValue(row.included_count ?? row.included),
      dropped: numberValue(row.dropped_count ?? row.dropped)
    };
  });

  const included = arrayValue(raw.included_sources ?? raw.included_items).map((row, index) => normalizeSource(row, index, "included", raw.drop_reasons));
  const dropped = arrayValue(raw.dropped_sources ?? raw.dropped_items).map((row, index) => normalizeSource(row, index, "dropped", raw.drop_reasons));

  return {
    totalBudget,
    used,
    sections: sectionRows,
    ...normalizeModelInput(raw, included),
    includedSources: included,
    droppedSources: dropped,
    fallbackReason: stringOrUndefined(raw.fallback_reason),
    warnings: arrayValue(raw.warnings).map((item) => String(item))
  };
}

function normalizeModelInput(raw: Record<string, unknown>, includedSources: ContextSourceRow[]): Pick<ContextReportView, "modelInputSections" | "modelInputCaptureMode"> {
  const previewSections = normalizeModelInputPreview(raw);
  if (previewSections.length) return { modelInputSections: previewSections, modelInputCaptureMode: "preview" };

  const modelInput = objectValue(raw.model_input);
  const explicitSections = arrayValue(raw.model_input_sections ?? raw.input_sections);
  const sectionsObject = objectValue(modelInput?.sections) || objectValue(raw.sections_text);
  const knownOrder = ["system", "markdown_memory", "capabilities", "conversation", "runtime_notes", "attachments"];

  if (explicitSections.length) {
    const sections = explicitSections.map((item, index) => {
      const row = objectValue(item) || {};
      const name = textValue(row.name ?? row.section ?? row.type, `section_${index + 1}`);
      const text = textValue(row.text ?? row.content ?? row.preview, "");
      return makeSection(name, text, row);
    }).filter((section) => section.text.trim().length > 0);
    if (sections.length) return { modelInputSections: sections, modelInputCaptureMode: "captured" };
  }

  if (sectionsObject) {
    const names = [...knownOrder.filter((name) => sectionsObject[name] !== undefined), ...Object.keys(sectionsObject).filter((name) => !knownOrder.includes(name))];
    const sections = names.map((name) => {
      const value = sectionsObject[name];
      const row = objectValue(value);
      const text = row ? textValue(row.text ?? row.content ?? row.preview, "") : textValue(value, "");
      return makeSection(name, text, row || {});
    }).filter((section) => section.text.trim().length > 0);
    if (sections.length) return { modelInputSections: sections, modelInputCaptureMode: "captured" };
  }

  const text = textValue(modelInput?.text ?? raw.model_input_text ?? raw.prompt_text, "");
  if (text.trim()) return { modelInputSections: [makeSection("model_input", text, modelInput || {})], modelInputCaptureMode: "captured" };

  const reconstructed = reconstructModelInputSections(includedSources, knownOrder);
  return {
    modelInputSections: reconstructed,
    modelInputCaptureMode: reconstructed.length ? "reconstructed" : "missing"
  };
}

function normalizeModelInputPreview(raw: Record<string, unknown>): ContextSection[] {
  const preview = objectValue(raw.model_input_preview);
  const sections = arrayValue(preview?.sections);
  return sections.map((item, index) => {
    const row = objectValue(item) || {};
    const name = textValue(row.name ?? row.section ?? row.role, `preview_${index + 1}`);
    const text = textValue(row.text ?? row.preview ?? row.content, "");
    return makeSection(name, text, {
      ...row,
      chars: row.chars,
      source_count: row.source_count ?? row.sources
    });
  }).filter((section) => section.text.trim().length > 0);
}

function makeSection(name: string, text: string, row: Record<string, unknown>): ContextSection {
  return {
    name,
    title: name.replace(/_/g, " "),
    text,
    chars: numberValue(row.chars ?? row.char_count) ?? text.length,
    tokens: numberValue(row.tokens ?? row.token_count),
    sources: numberValue(row.source_count ?? row.sources)
  };
}

function normalizeSource(value: unknown, index: number, kind: "included" | "dropped", dropReasons?: unknown): ContextSourceRow {
  const row = objectValue(value) || {};
  const source = textValue(row.source ?? row.name ?? row.path ?? row.id, `${kind}:${index + 1}`);
  const dropReasonMap = objectValue(dropReasons);
  return {
    source,
    section: textValue(row.section ?? row.kind ?? row.type, "Not captured"),
    chars: numberValue(row.chars ?? row.length ?? row.used_chars),
    tokens: numberValue(row.tokens ?? row.used ?? row.used_tokens),
    reason: textValue(row.reason ?? dropReasonMap?.[source], kind === "dropped" ? "No reason recorded" : "No reason recorded"),
    preview: textValue(row.preview ?? row.text_preview ?? row.snippet ?? row.text, "Empty"),
    raw: row
  };
}

function reconstructModelInputSections(rows: ContextSourceRow[], knownOrder: string[]): ContextSection[] {
  const grouped = new Map<string, ContextSourceRow[]>();
  for (const row of rows) {
    const text = sourceText(row);
    if (!text.trim()) continue;
    const section = row.section && row.section !== "Not captured" ? row.section : "uncategorized";
    grouped.set(section, [...(grouped.get(section) || []), row]);
  }

  const names = [...knownOrder.filter((name) => grouped.has(name)), ...Array.from(grouped.keys()).filter((name) => !knownOrder.includes(name))];
  return names.map((name) => {
    const sectionRows = grouped.get(name) || [];
    const text = sectionRows.map((row) => {
      const header = row.source ? `# ${row.source}` : "# Source";
      return `${header}\n${sourceText(row)}`;
    }).join("\n\n");
    const chars = sectionRows.reduce((total, row) => total + (row.chars ?? sourceText(row).length), 0);
    const tokens = sectionRows.reduce((total, row) => total + (row.tokens || 0), 0);
    return {
      name,
      title: `${name.replace(/_/g, " ")} preview`,
      text,
      chars,
      tokens: tokens > 0 ? tokens : null,
      sources: sectionRows.length
    };
  }).filter((section) => section.text.trim().length > 0);
}

function sourceText(row: ContextSourceRow) {
  const rawText = textValue(row.raw.text ?? row.raw.content ?? row.raw.body ?? row.raw.value ?? row.raw.preview ?? row.raw.text_preview ?? row.raw.snippet, "");
  if (rawText.trim()) return rawText;
  return row.preview === "Empty" ? "" : row.preview;
}

function sanitizePrivateReasoning(value: unknown): unknown {
  if (Array.isArray(value)) return value.map((item) => sanitizePrivateReasoning(item));
  if (!value || typeof value !== "object") return value;
  const result: Record<string, unknown> = {};
  for (const [key, child] of Object.entries(value as Record<string, unknown>)) {
    const lower = key.toLowerCase();
    if (
      lower.includes("reasoning_delta") ||
      lower.includes("chain_of_thought") ||
      lower === "cot" ||
      lower === "think" ||
      lower === "thinking"
    ) {
      result[key] = "[hidden private reasoning]";
      continue;
    }
    if (typeof child === "string" && /<think>[\s\S]*?<\/think>/i.test(child)) {
      result[key] = child.replace(/<think>[\s\S]*?<\/think>/gi, "[hidden private reasoning]");
      continue;
    }
    result[key] = sanitizePrivateReasoning(child);
  }
  return result;
}

function objectValue(value: unknown): Record<string, unknown> | null {
  return value && typeof value === "object" && !Array.isArray(value) ? value as Record<string, unknown> : null;
}

function arrayValue(value: unknown): unknown[] {
  return Array.isArray(value) ? value : [];
}

function numberValue(value: unknown): number | null {
  if (typeof value === "number" && Number.isFinite(value)) return value;
  if (typeof value === "string" && value.trim() && Number.isFinite(Number(value))) return Number(value);
  return null;
}

function stringOrUndefined(value: unknown): string | undefined {
  if (typeof value !== "string" || !value.trim()) return undefined;
  return value;
}
