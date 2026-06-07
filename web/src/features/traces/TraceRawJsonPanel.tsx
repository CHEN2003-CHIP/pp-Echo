import type { TraceDetail } from "../../api";
import { safeJsonStringify } from "./trace-utils";

export function TraceRawJsonPanel({ detail }: { detail: TraceDetail | null }) {
  return <section className="trace-inspect-section"><details><summary>Raw JSON</summary><pre>{safeJsonStringify(detail)}</pre></details></section>;
}
