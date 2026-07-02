import { ChevronDown, ChevronRight, Copy } from "lucide-react";
import { useState } from "react";
import type { TraceDetail } from "../../api";
import { findContextReport, type ContextReportView, type ContextSection, type ContextSourceRow, metricValue, textValue } from "./trace-display";
import { EmptyState } from "./EmptyState";
import { StatusBadge } from "./StatusBadge";

export function ContextInspector({ detail }: { detail: TraceDetail }) {
  const report = findContextReport(detail);
  return (
    <div className="trace-context-stack">
      <div className="trace-context-grid">
        <ContextBudgetCard report={report} />
        <ContextSectionBars report={report} />
      </div>
      <ModelInputPreview sections={report.modelInputSections} captureMode={report.modelInputCaptureMode} />
      <IncludedSourcesTable rows={report.includedSources} />
      <DroppedSourcesList rows={report.droppedSources} />
      {report.fallbackReason || report.warnings.length ? (
        <div className="trace-card trace-soft-panel">
          {report.fallbackReason ? <p><strong>Fallback</strong><span>{report.fallbackReason}</span></p> : null}
          {report.warnings.map((warning) => <p key={warning}><strong>Warning</strong><span>{warning}</span></p>)}
        </div>
      ) : null}
    </div>
  );
}

export function ContextBudgetCard({ report }: { report: ContextReportView }) {
  const used = report.used;
  const budget = report.totalBudget;
  const pct = budget && used !== null ? Math.min(100, Math.round((used / budget) * 100)) : 0;
  return (
    <section className="trace-budget-card">
      <div className="trace-budget-top">
        <div>
          <span>Context budget</span>
          <strong>{used !== null ? used.toLocaleString() : "Not captured"} / {budget !== null ? budget.toLocaleString() : "Not captured"}</strong>
        </div>
        <em>{budget ? `${pct}% used` : "No budget report"}</em>
      </div>
      <div className="trace-progress"><i style={{ width: `${pct}%` }} /></div>
    </section>
  );
}

export function ContextSectionBars({ report }: { report: ContextReportView }) {
  return (
    <section className="trace-section-bars">
      {report.sections.map((section) => {
        const pct = section.budget && section.used !== null ? Math.min(100, Math.round((section.used / section.budget) * 100)) : 0;
        return (
          <article key={section.name} className="trace-section-row">
            <div className="trace-section-top">
              <strong>{section.name}</strong>
              <span>{metricValue(section.used)} / {metricValue(section.budget)}</span>
            </div>
            <div className="trace-section-meta">included {metricValue(section.included, "0")} / dropped {metricValue(section.dropped, "0")}</div>
            <div className="trace-mini-progress"><i style={{ width: `${pct}%` }} /></div>
          </article>
        );
      })}
      {!report.sections.length ? <EmptyState title="No section budget records">Section-level budget data was not captured for this run.</EmptyState> : null}
    </section>
  );
}

export function ModelInputPreview({ sections, captureMode }: { sections: ContextSection[]; captureMode: ContextReportView["modelInputCaptureMode"] }) {
  const label = captureMode === "captured" ? "Captured" : captureMode === "preview" ? "Preview" : captureMode === "reconstructed" ? "Reconstructed" : "Not captured";
  return (
    <section className="trace-card">
      <div className="trace-card-header">
        <div>
          <h2>Model Input Preview</h2>
          <p>{captureMode === "preview" ? "Trace-safe preview grouped by section" : captureMode === "reconstructed" ? "Reconstructed from included sources by section" : "Context text grouped by section"}</p>
        </div>
        <span className={`trace-badge ${captureMode === "reconstructed" ? "trace-badge-neutral" : "trace-badge-primary"}`}>{label}</span>
      </div>
      <div className="trace-card-body trace-input-preview">
        {sections.map((section) => <ModelInputSectionCard key={section.name} section={section} />)}
        {!sections.length ? <EmptyState title="Model input text was not captured for this run." /> : null}
      </div>
    </section>
  );
}

export function ModelInputSectionCard({ section }: { section: ContextSection }) {
  const [expanded, setExpanded] = useState(section.text.length < 900);
  const body = expanded ? section.text : `${section.text.slice(0, 900)}${section.text.length > 900 ? "\n..." : ""}`;
  return (
    <article className="trace-prompt-section">
      <header>
        <button type="button" className="trace-icon-button" onClick={() => setExpanded((value) => !value)} title={expanded ? "Collapse" : "Expand"}>
          {expanded ? <ChevronDown size={15} /> : <ChevronRight size={15} />}
        </button>
        <div>
          <strong><span className="trace-pill">{section.name}</span>{section.title}</strong>
          <small>{section.chars.toLocaleString()} chars{section.tokens !== null ? ` / ${section.tokens.toLocaleString()} tokens` : ""}{section.sources !== null ? ` / ${section.sources} sources` : ""}</small>
        </div>
        <button type="button" className="trace-copy-button" onClick={() => navigator.clipboard?.writeText(section.text).catch(() => undefined)}><Copy size={13} />Copy</button>
      </header>
      <pre>{body}</pre>
    </article>
  );
}

export function IncludedSourcesTable({ rows }: { rows: ContextSourceRow[] }) {
  return (
    <section className="trace-card">
      <div className="trace-card-header">
        <div>
          <h2>Included Sources</h2>
          <p>Sources that entered model context</p>
        </div>
        <span className="trace-badge trace-badge-neutral">{rows.length} sources</span>
      </div>
      <div className="trace-card-body trace-table-wrap">
        {rows.length ? (
          <table className="trace-source-table">
            <thead><tr><th>Source</th><th>Section</th><th>Chars</th><th>Reason</th><th>Preview</th><th>Actions</th></tr></thead>
            <tbody>{rows.map((row, index) => <SourceRow key={`${row.source}-${index}`} row={row} />)}</tbody>
          </table>
        ) : <EmptyState title="No included sources">Source inclusion records were not captured.</EmptyState>}
      </div>
    </section>
  );
}

export function DroppedSourcesList({ rows }: { rows: ContextSourceRow[] }) {
  return (
    <section className="trace-card">
      <div className="trace-card-header">
        <div>
          <h2>Dropped Sources</h2>
          <p>Candidate context that did not enter the final prompt</p>
        </div>
        <StatusBadge status={rows.length ? "warning" : "ok"} label={rows.length ? `${rows.length} dropped` : "None"} />
      </div>
      <div className="trace-card-body trace-dropped-list">
        {rows.map((row, index) => (
          <article key={`${row.source}-${index}`} className="trace-section-row">
            <div className="trace-section-top">
              <strong className="trace-source-id">{row.source}</strong>
              <span className="trace-badge trace-badge-warn">{row.reason || "No reason recorded"}</span>
            </div>
            <div className="trace-section-meta">{row.section} / {row.preview || "Empty"}</div>
          </article>
        ))}
        {!rows.length ? <EmptyState title="No dropped sources" /> : null}
      </div>
    </section>
  );
}

function SourceRow({ row }: { row: ContextSourceRow }) {
  const chars = row.chars !== null ? row.chars.toLocaleString() : row.tokens !== null ? `${row.tokens.toLocaleString()} tokens` : "Not captured";
  return (
    <tr>
      <td className="trace-source-id">{row.source}</td>
      <td>{textValue(row.section)}</td>
      <td>{chars}</td>
      <td>{row.reason || "No reason recorded"}</td>
      <td className="trace-source-preview">{row.preview || "Empty"}</td>
      <td><button type="button" className="trace-copy-button" onClick={() => navigator.clipboard?.writeText(JSON.stringify(row.raw, null, 2)).catch(() => undefined)}>Copy</button></td>
    </tr>
  );
}
