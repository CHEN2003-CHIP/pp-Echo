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
};

export function TraceContextBudgetPanel({ detail }: { detail: TraceDetail }) {
  const record = extractContextBudget(detail);
  if (!record) {
    return <section className="trace-inspect-section"><h3>Context Budget</h3><p className="muted">No context budget report.</p></section>;
  }
  const report = record.report;
  const sections = Object.entries(report.per_section || {});
  const dropped = report.dropped_items || [];
  return (
    <section className="trace-inspect-section">
      <h3>Context Budget</h3>
      <p className="muted">
        used {String(report.used || 0)} / {String(report.total_budget || 0)} chars
        {record.coreMemoryBudgetError ? " | core memory budget warning" : ""}
      </p>
      <details open>
        <summary>Sections ({sections.length})</summary>
        <pre>{safeJsonStringify(sectionSummary(sections))}</pre>
      </details>
      <details>
        <summary>Included Sources ({(report.included_items || []).length})</summary>
        <pre>{safeJsonStringify(report.included_items || [])}</pre>
      </details>
      <details open={dropped.length > 0}>
        <summary>Dropped Sources ({dropped.length})</summary>
        <pre>{safeJsonStringify(dropped)}</pre>
      </details>
    </section>
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
function sectionSummary(sections: Array<[string, SectionUsage]>) {
  const summary: Record<string, Record<string, number>> = {};
  sections.forEach(([name, usage]) => {
    summary[name] = {
      budget: usage.budget || 0,
      used: usage.used || 0,
      included: usage.included_count || 0,
      dropped: usage.dropped_count || 0
    };
  });
  return summary;
}

