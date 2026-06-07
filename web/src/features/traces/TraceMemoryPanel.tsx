import type { TraceSpan } from "../../api";
import { TraceSpanList } from "./TraceToolCallsPanel";

export function TraceMemoryPanel({ spans }: { spans: TraceSpan[] }) {
  return <TraceSpanList title="Memory" spans={spans.filter((span) => span.span_type === "memory")} renderMeta={(span) => `returned ${String(span.output.returned_count || 0)}`} />;
}
