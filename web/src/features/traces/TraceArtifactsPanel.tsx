import type { TraceArtifact } from "../../api";
import { safeJsonStringify } from "./trace-utils";

export function TraceArtifactsPanel({ artifacts }: { artifacts: TraceArtifact[] }) {
  return <section className="trace-inspect-section"><h3>Artifacts / Changed Files</h3>{artifacts.map((artifact) => <pre key={artifact.artifact_id}>{safeJsonStringify(artifact)}</pre>)}{artifacts.length === 0 ? <p className="muted">No artifacts.</p> : null}</section>;
}
