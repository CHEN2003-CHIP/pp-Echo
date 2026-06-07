import type { TraceSpan } from "../../api";
import { groupApprovalSpansByDigest, statusLabel } from "./trace-utils";

export function TraceApprovalPanel({ spans }: { spans: TraceSpan[] }) {
  const groups = groupApprovalSpansByDigest(spans);
  return (
    <section className="trace-inspect-section trace-span-list">
      <h3>Approvals</h3>
      {groups.map((group) => <details key={group.digest}><summary>{group.digest}</summary>{group.items.map((span) => <p key={span.span_id}>{span.name} · {statusLabel(span.status)} · {String(span.attributes.decision || "")}</p>)}</details>)}
      {groups.length === 0 ? <p className="muted">No approvals.</p> : null}
    </section>
  );
}
