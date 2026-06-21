import type { TraceDetail } from "../../api";

type CapabilityMap = Record<string, boolean | string | number | null | undefined>;

export type ModelRuntimeSelection = {
  providerId: string;
  modelId: string;
  runtimeId: string;
  modelProfileSource: string;
  runtimeProfileSource: string;
  modelCapabilities: CapabilityMap;
  runtimeSupports: CapabilityMap;
};

export const TRACE_MODEL_RUNTIME_EMPTY = "No model/runtime selection metadata recorded for this run.";

export function TraceModelRuntimeCard({ detail }: { detail: TraceDetail }) {
  const selection = extractModelRuntimeSelection(detail);
  if (!selection) {
    return (
      <section className="trace-inspect-section trace-model-runtime-card">
        <h3>Model / Runtime</h3>
        <p className="muted">{TRACE_MODEL_RUNTIME_EMPTY}</p>
      </section>
    );
  }
  return (
    <section className="trace-inspect-section trace-model-runtime-card">
      <div className="trace-model-runtime-head">
        <div>
          <span>Provider</span>
          <strong>{selection.providerId}</strong>
        </div>
        <div>
          <span>Model</span>
          <strong>{selection.modelId}</strong>
        </div>
        <div>
          <span>Runtime</span>
          <strong>{selection.runtimeId}</strong>
        </div>
        <div>
          <span>Profile Source</span>
          <strong>{selection.modelProfileSource} / {selection.runtimeProfileSource}</strong>
        </div>
      </div>
      <div className="trace-model-runtime-grids">
        <CapabilityGroup title="Model capabilities" values={selection.modelCapabilities} />
        <CapabilityGroup title="Runtime supports" values={selection.runtimeSupports} />
      </div>
    </section>
  );
}

export function extractModelRuntimeSelection(detail: TraceDetail): ModelRuntimeSelection | null {
  /*
   * Trace details can come from new runs, old summaries, or raw event payloads.
   * This helper centralizes the fallback order so the visual component stays simple
   * and old traces render a friendly empty state instead of throwing on missing data.
   */
  const eventDetails = firstRecord(detail.events.find((event) => event.name === "model_runtime_selected")?.payload?.details);
  const runAttributes = firstRecord(detail.run?.attributes);
  const summaryAttributes = firstRecord(detail.summary?.attributes);
  const source = mergeRecords(summaryAttributes, runAttributes, eventDetails);
  const modelCapabilities = capabilityMap(source.model_capabilities);
  const runtimeSupports = capabilityMap(source.runtime_supports);
  const providerId = textValue(source.provider_id ?? detail.summary?.provider ?? detail.run?.provider);
  const modelId = textValue(source.model_id ?? detail.summary?.model ?? detail.run?.model);
  const runtimeId = textValue(source.runtime_id);
  if (!providerId && !modelId && !runtimeId && Object.keys(modelCapabilities).length === 0 && Object.keys(runtimeSupports).length === 0) {
    return null;
  }
  return {
    providerId: providerId || "-",
    modelId: modelId || "-",
    runtimeId: runtimeId || "-",
    modelProfileSource: textValue(source.model_profile_source) || "-",
    runtimeProfileSource: textValue(source.runtime_profile_source) || "-",
    modelCapabilities,
    runtimeSupports,
  };
}

function CapabilityGroup({ title, values }: { title: string; values: CapabilityMap }) {
  const entries = Object.entries(values);
  return (
    <div className="trace-model-runtime-group">
      <h4>{title}</h4>
      <div>
        {entries.length ? entries.map(([key, value]) => (
          <span key={key} className={value === true ? "enabled" : value === false ? "disabled" : ""}>
            {formatLabel(key)}: {formatValue(value)}
          </span>
        )) : <span className="disabled">No metadata</span>}
      </div>
    </div>
  );
}

function mergeRecords(...records: Record<string, unknown>[]): Record<string, unknown> {
  return Object.assign({}, ...records);
}

function firstRecord(value: unknown): Record<string, unknown> {
  return value && typeof value === "object" && !Array.isArray(value) ? value as Record<string, unknown> : {};
}

function capabilityMap(value: unknown): CapabilityMap {
  const raw = firstRecord(value);
  const normalized: CapabilityMap = {};
  for (const [key, item] of Object.entries(raw)) {
    if (typeof item === "boolean" || typeof item === "string" || typeof item === "number" || item == null) {
      normalized[key] = item;
    }
  }
  return normalized;
}

function textValue(value: unknown): string {
  return typeof value === "string" || typeof value === "number" ? String(value) : "";
}

function formatLabel(value: string): string {
  return value.replace(/_/g, " ");
}

function formatValue(value: unknown): string {
  if (value === true) return "yes";
  if (value === false) return "no";
  if (value === null || value === undefined || value === "") return "-";
  return String(value);
}
