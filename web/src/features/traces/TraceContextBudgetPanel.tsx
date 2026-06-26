import type { TraceDetail, TraceSpan } from "../../api";
import { safeJsonStringify } from "./trace-utils";

type SectionUsage = {
  budget?: number;
  used?: number;
  included_count?: number;
  dropped_count?: number;
};

type BudgetReport = {
  total_budget?: number;
  used?: number;
  per_section?: Record<string, SectionUsage>;
  included_items?: Array<Record<string, unknown>>;
  dropped_items?: Array<Record<string, unknown>>;
  drop_reasons?: Record<string, string>;
  fallback_reason?: string;
  warnings?: string[];
};

export function TraceContextBudgetPanel({ detail }: { detail: TraceDetail }) {
  const record = extractContextBudget(detail);
  if (!record) {
    return <section className="trace-inspect-section"><h3>Context Budget</h3><p className="muted">No context budget report.</p></section>;
  }
  const report = record.report;
  const total = report.total_budget || 0;
  const used = report.used || 0;
  const pct = total > 0 ? Math.min(100, Math.round((used / total) * 100)) : 0;
  const sections = Object.entries(report.per_section || {});
  const included = report.included_items || [];
  const dropped = report.dropped_items || [];
  const warnings = [...(report.warnings || []), ...(record.coreMemoryBudgetError ? ["Core memory budget warning"] : [])];

  return (
    <section className="trace-inspect-section trace-context-budget">
      <h3>Context Budget</h3>
      <div className="trace-budget-overview">
        <strong>{used.toLocaleString()} / {total.toLocaleString()}</strong>
        <span>{pct}% used</span>
      </div>
      <BudgetBar value={used} total={total} />
      <div className="trace-budget-sections">
        {sections.map(([name, usage]) => (
          <div key={name}>
            <div><strong>{name}</strong><span>{Number(usage.used || 0).toLocaleString()} / {Number(usage.budget || 0).toLocaleString()}</span></div>
            <BudgetBar value={usage.used || 0} total={usage.budget || total} />
            <small>included {usage.included_count || 0} | dropped {usage.dropped_count || 0}</small>
          </div>
        ))}
      </div>
      {sections.length === 0 ? <p className="muted">No section usage records.</p> : null}
      <SourceTable title="Included Sources" rows={included} />
      <SourceTable title="Dropped Sources" rows={dropped} dropReasons={report.drop_reasons || {}} />
      {report.fallback_reason || warnings.length ? (
        <div className="trace-budget-warnings">
          {report.fallback_reason ? <p><strong>Fallback</strong><span>{report.fallback_reason}</span></p> : null}
          {warnings.map((warning) => <p key={warning}><strong>Warning</strong><span>{warning}</span></p>)}
        </div>
      ) : null}
      <details>
        <summary>Raw budget report</summary>
        <pre>{safeJsonStringify(report)}</pre>
      </details>
    </section>
  );
}

function BudgetBar({ value, total }: { value: number; total: number }) {
  const width = total > 0 ? Math.min(100, Math.max(0, (value / total) * 100)) : 0;
  return <div className="trace-budget-bar" aria-label={`${Math.round(width)}%`}><span style={{ width: `${width}%` }} /></div>;
}

function SourceTable({ title, rows, dropReasons }: { title: string; rows: Array<Record<string, unknown>>; dropReasons?: Record<string, string> }) {
  return (
    <div className="trace-source-table">
      <h4>{title}</h4>
      {rows.length ? (
        <table>
          <thead><tr><th>Source</th><th>Section</th><th>Tokens/Chars</th><th>Reason</th></tr></thead>
          <tbody>
            {rows.map((row, index) => {
              const source = textValue(row.source || row.name || row.path || row.id || `#${index + 1}`);
              return (
                <tr key={`${source}-${index}`}>
                  <td>{source}</td>
                  <td>{textValue(row.section ?? row.kind ?? row.type)}</td>
                  <td>{textValue(row.used ?? row.tokens ?? row.chars ?? row.length)}</td>
                  <td>{textValue(row.reason ?? dropReasons?.[source])}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      ) : <p className="muted">No {title.toLowerCase()}.</p>}
    </div>
  );
}

function extractContextBudget(detail: TraceDetail): { report: BudgetReport; coreMemoryBudgetError: boolean } | null {
  const span = [...detail.spans].reverse().find((item: TraceSpan) => item.name === "context.build" || item.span_type === "context");
  if (span?.output?.context_payload_version !== 2) {
    return null;
  }
  const context = objectValue(span.output.context);
  const report = objectValue(context?.budget_report);
  if (!context || !report) return null;
  return { report: report as BudgetReport, coreMemoryBudgetError: Boolean(context.core_memory_budget_error || span.attributes?.core_memory_budget_error) };
}

function objectValue(value: unknown): Record<string, unknown> | null {
  return value && typeof value === "object" && !Array.isArray(value) ? value as Record<string, unknown> : null;
}

function textValue(value: unknown) {
  if (value === null || value === undefined || value === "") return "-";
  return String(value);
}
