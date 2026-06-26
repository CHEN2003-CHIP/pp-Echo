import { useMemo, useState } from "react";
import type { TraceSpan } from "../../api";
import { formatDuration, safeJsonStringify, statusLabel, statusTone } from "./trace-utils";

type ToolFilter = "all" | "errors" | "changed" | "approval" | "shell";

function dedupeToolSpans(spans: TraceSpan[]) {
  const selected = new Map<string, TraceSpan>();
  const anonymous: TraceSpan[] = [];
  for (const span of spans.filter((item) => item.span_type === "tool")) {
    const id = String(span.attributes.tool_call_id || "");
    if (!id) {
      anonymous.push(span);
      continue;
    }
    const current = selected.get(id);
    if (!current || (span.attributes.source === "tool_registry_middleware" && current.attributes.source !== "tool_registry_middleware")) {
      selected.set(id, span);
    }
  }
  return [...selected.values(), ...anonymous];
}

export function TraceToolCallsPanel({ spans, selectedSpanId, onSelectSpan }: { spans: TraceSpan[]; selectedSpanId?: string | null; onSelectSpan?: (span: TraceSpan) => void }) {
  const [filter, setFilter] = useState<ToolFilter>("all");
  const tools = useMemo(() => dedupeToolSpans(spans), [spans]);
  const filtered = tools.filter((span) => matchesFilter(span, filter));
  const filters: Array<[ToolFilter, string]> = [["all", "All"], ["errors", "Errors"], ["changed", "Changed files"], ["approval", "Approval required"], ["shell", "Shell"]];

  return (
    <section className="trace-inspect-section trace-tool-panel">
      <div className="trace-section-title">
        <h3>Tool Calls</h3>
        <div className="trace-filter-pills" role="tablist" aria-label="Tool call filters">
          {filters.map(([value, label]) => (
            <button key={value} className={filter === value ? "active" : ""} onClick={() => setFilter(value)}>{label}</button>
          ))}
        </div>
      </div>
      <div className="trace-tool-table-wrap">
        <table className="trace-tool-table">
          <thead>
            <tr>
              <th>Tool</th>
              <th>Status</th>
              <th>Duration</th>
              <th>Permission</th>
              <th>Requires approval</th>
              <th>Changed paths</th>
              <th>Source</th>
              <th>Error</th>
            </tr>
          </thead>
          <tbody>
            {filtered.map((span) => {
              const changed = changedPaths(span);
              return (
                <tr key={span.span_id} className={span.span_id === selectedSpanId ? "active" : ""} onClick={() => onSelectSpan?.(span)}>
                  <td>{String(span.attributes.tool_name ?? span.name ?? "-")}</td>
                  <td><em className={`trace-status-${statusTone(span.status)}`}>{statusLabel(span.status)}</em></td>
                  <td>{formatDuration(span.duration_ms)}</td>
                  <td>{textValue(span.attributes.permission ?? span.attributes.permission_level ?? span.attributes.risk_level)}</td>
                  <td>{requiresApproval(span) ? "Yes" : "No"}</td>
                  <td title={changed.join("\n")}>{changed.length ? changed.join(", ") : "-"}</td>
                  <td>{textValue(span.attributes.source)}</td>
                  <td>{span.error_message || textValue(span.output.error ?? span.output.error_message)}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      {filtered.length === 0 ? <p className="muted">No tool calls for this filter.</p> : null}
    </section>
  );
}

export function TraceSpanList({ title, spans, renderMeta, selectedSpanId, onSelectSpan }: { title: string; spans: TraceSpan[]; renderMeta: (span: TraceSpan) => string; selectedSpanId?: string | null; onSelectSpan?: (span: TraceSpan) => void }) {
  return (
    <section className="trace-inspect-section trace-span-list">
      <h3>{title}</h3>
      {spans.map((span) => (
        <details key={span.span_id} className={span.span_id === selectedSpanId ? "active" : ""}>
          <summary onClick={() => onSelectSpan?.(span)}>{renderMeta(span)}</summary>
          <pre>{safeJsonStringify({ input: span.input, output: span.output, attributes: span.attributes })}</pre>
        </details>
      ))}
      {spans.length === 0 ? <p className="muted">No records.</p> : null}
    </section>
  );
}

function matchesFilter(span: TraceSpan, filter: ToolFilter) {
  if (filter === "errors") return span.status === "error" || Boolean(span.error_message || span.output.error || span.output.error_message);
  if (filter === "changed") return changedPaths(span).length > 0;
  if (filter === "approval") return requiresApproval(span);
  if (filter === "shell") return String(span.attributes.tool_name ?? span.name ?? "").toLowerCase().includes("shell");
  return true;
}

function changedPaths(span: TraceSpan): string[] {
  const raw = span.output.changed_paths || span.attributes.changed_paths;
  return Array.isArray(raw) ? raw.map((item) => String(item)).filter(Boolean) : [];
}

function requiresApproval(span: TraceSpan) {
  return Boolean(span.attributes.requires_approval || span.attributes.approval_required || span.output.requires_approval || span.output.approval_required);
}

function textValue(value: unknown) {
  if (value === null || value === undefined || value === "") return "-";
  return String(value);
}
