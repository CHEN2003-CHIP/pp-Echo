"use strict";
Object.defineProperty(exports, "__esModule", { value: true });
exports.TraceCapabilityPanel = TraceCapabilityPanel;
const jsx_runtime_1 = require("react/jsx-runtime");
const trace_utils_1 = require("./trace-utils");
function TraceCapabilityPanel({ detail }) {
    const events = capabilityEvents(detail.events);
    return ((0, jsx_runtime_1.jsxs)("section", { className: "trace-inspect-section trace-span-list", children: [(0, jsx_runtime_1.jsx)("h3", { children: "Capabilities" }), events.map((event) => ((0, jsx_runtime_1.jsxs)("details", { children: [(0, jsx_runtime_1.jsxs)("summary", { children: ["selected:", event.selected.length, " blocked:", event.blocked.length, " trust:", String(event.context.trust_level || "-")] }), (0, jsx_runtime_1.jsx)("pre", { children: (0, trace_utils_1.safeJsonStringify)({ selected: event.selected, blocked: event.blocked, policy_context: event.context }) })] }, event.key))), events.length === 0 ? (0, jsx_runtime_1.jsx)("p", { className: "muted", children: "No capability selection records." }) : null] }));
}
function capabilityEvents(events) {
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
function objectValue(value) {
    return value && typeof value === "object" && !Array.isArray(value) ? value : {};
}
function arrayOfObjects(value) {
    return Array.isArray(value) ? value.filter((item) => item && typeof item === "object" && !Array.isArray(item)) : [];
}
