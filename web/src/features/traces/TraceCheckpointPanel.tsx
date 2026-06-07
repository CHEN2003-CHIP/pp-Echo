import type { TraceSpan } from "../../api";
import { TraceSpanList } from "./TraceToolCallsPanel";

export function TraceCheckpointPanel({ spans }: { spans: TraceSpan[] }) {
  return <TraceSpanList title="Checkpoints" spans={spans.filter((span) => span.span_type === "checkpoint")} renderMeta={(span) => `${span.name} · ${String(span.attributes.checkpoint_id || span.attributes.reason || "")}`} />;
}
