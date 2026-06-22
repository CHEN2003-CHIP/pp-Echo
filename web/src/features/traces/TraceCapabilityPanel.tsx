import type { TraceDetail, TraceEvent } from "../../api";
import { safeJsonStringify } from "./trace-utils";

type CapabilityEventSummary = {
  key: string;
  selected: Array<Record<string, unknown>>;
  blocked: Array<Record<string, unknown>>;
  context: Record<string, unknown>;
};

export function TraceCapabilityPanel({ detail }: { detail: TraceDetail }) {
  const events = capabilityEvents(detail.events);
  return (
    <section className="trace-inspect-section trace-span-list">
      <h3>Capabilities</h3>
      {events.map((event) => (
        <details key={event.key}>
          <summary>
            selected:{event.selected.length} blocked:{event.blocked.length} trust:{String(event.context.trust_level || "-")}
          </summary>
          <pre>{safeJsonStringify({ selected: event.selected, blocked: event.blocked, policy_context: event.context })}</pre>
        </details>
      ))}
      {events.length === 0 ? <p className="muted">No capability selection records.</p> : null}
    </section>
  );
}

function capabilityEvents(events: TraceEvent[]): CapabilityEventSummary[] {
  /*
   * Extract capability_selected payloads from trace events with old/new payload tolerance.
   * Current traces wrap lifecycle details under payload.details; future traces may store
   * selected/blocked directly at payload top level.
   */
  return events
    .filter((event) => event.name === "capability_selected" || event.payload?.type === "capability_selected")
    .map((event) => {
      const details = objectValue(event.payload.details);
      const payload = event.payload.type === "capability_selected" ? event.payload : details;
      return {
        key: event.event_id,
        selected: arrayOfObjects(payload.selected),
        blocked: arrayOfObjects(payload.blocked),
        context: objectValue(payload.policy_context)
      };
    });
}

function objectValue(value: unknown): Record<string, unknown> {
  return value && typeof value === "object" && !Array.isArray(value) ? value as Record<string, unknown> : {};
}

function arrayOfObjects(value: unknown): Array<Record<string, unknown>> {
  return Array.isArray(value) ? value.filter((item) => item && typeof item === "object" && !Array.isArray(item)) as Array<Record<string, unknown>> : [];
}
