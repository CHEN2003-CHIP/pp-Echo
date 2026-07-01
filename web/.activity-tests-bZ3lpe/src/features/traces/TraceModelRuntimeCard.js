"use strict";
Object.defineProperty(exports, "__esModule", { value: true });
exports.TRACE_MODEL_RUNTIME_EMPTY = void 0;
exports.TraceModelRuntimeCard = TraceModelRuntimeCard;
exports.extractModelRuntimeSelection = extractModelRuntimeSelection;
const jsx_runtime_1 = require("react/jsx-runtime");
exports.TRACE_MODEL_RUNTIME_EMPTY = "No model/runtime selection metadata recorded for this run.";
function TraceModelRuntimeCard({ detail }) {
    const selection = extractModelRuntimeSelection(detail);
    if (!selection) {
        return ((0, jsx_runtime_1.jsxs)("section", { className: "trace-inspect-section trace-model-runtime-card", children: [(0, jsx_runtime_1.jsx)("h3", { children: "Model / Runtime" }), (0, jsx_runtime_1.jsx)("p", { className: "muted", children: exports.TRACE_MODEL_RUNTIME_EMPTY })] }));
    }
    return ((0, jsx_runtime_1.jsxs)("section", { className: "trace-inspect-section trace-model-runtime-card", children: [(0, jsx_runtime_1.jsxs)("div", { className: "trace-model-runtime-head", children: [(0, jsx_runtime_1.jsxs)("div", { children: [(0, jsx_runtime_1.jsx)("span", { children: "Provider" }), (0, jsx_runtime_1.jsx)("strong", { children: selection.providerId })] }), (0, jsx_runtime_1.jsxs)("div", { children: [(0, jsx_runtime_1.jsx)("span", { children: "Model" }), (0, jsx_runtime_1.jsx)("strong", { children: selection.modelId })] }), (0, jsx_runtime_1.jsxs)("div", { children: [(0, jsx_runtime_1.jsx)("span", { children: "Runtime" }), (0, jsx_runtime_1.jsx)("strong", { children: selection.runtimeId })] }), (0, jsx_runtime_1.jsxs)("div", { children: [(0, jsx_runtime_1.jsx)("span", { children: "Profile Source" }), (0, jsx_runtime_1.jsxs)("strong", { children: [selection.modelProfileSource, " / ", selection.runtimeProfileSource] })] })] }), (0, jsx_runtime_1.jsxs)("div", { className: "trace-model-runtime-grids", children: [(0, jsx_runtime_1.jsx)(CapabilityGroup, { title: "Model capabilities", values: selection.modelCapabilities }), (0, jsx_runtime_1.jsx)(CapabilityGroup, { title: "Runtime supports", values: selection.runtimeSupports })] })] }));
}
function extractModelRuntimeSelection(detail) {
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
function CapabilityGroup({ title, values }) {
    const entries = Object.entries(values);
    return ((0, jsx_runtime_1.jsxs)("div", { className: "trace-model-runtime-group", children: [(0, jsx_runtime_1.jsx)("h4", { children: title }), (0, jsx_runtime_1.jsx)("div", { children: entries.length ? entries.map(([key, value]) => ((0, jsx_runtime_1.jsxs)("span", { className: value === true ? "enabled" : value === false ? "disabled" : "", children: [formatLabel(key), ": ", formatValue(value)] }, key))) : (0, jsx_runtime_1.jsx)("span", { className: "disabled", children: "No metadata" }) })] }));
}
function mergeRecords(...records) {
    return Object.assign({}, ...records);
}
function firstRecord(value) {
    return value && typeof value === "object" && !Array.isArray(value) ? value : {};
}
function capabilityMap(value) {
    const raw = firstRecord(value);
    const normalized = {};
    for (const [key, item] of Object.entries(raw)) {
        if (typeof item === "boolean" || typeof item === "string" || typeof item === "number" || item == null) {
            normalized[key] = item;
        }
    }
    return normalized;
}
function textValue(value) {
    return typeof value === "string" || typeof value === "number" ? String(value) : "";
}
function formatLabel(value) {
    return value.replace(/_/g, " ");
}
function formatValue(value) {
    if (value === true)
        return "yes";
    if (value === false)
        return "no";
    if (value === null || value === undefined || value === "")
        return "-";
    return String(value);
}
