"use strict";
Object.defineProperty(exports, "__esModule", { value: true });
exports.TraceArtifactsPanel = TraceArtifactsPanel;
const jsx_runtime_1 = require("react/jsx-runtime");
const trace_utils_1 = require("./trace-utils");
function TraceArtifactsPanel({ artifacts }) {
    return (0, jsx_runtime_1.jsxs)("section", { className: "trace-inspect-section", children: [(0, jsx_runtime_1.jsx)("h3", { children: "Artifacts / Changed Files" }), artifacts.map((artifact) => (0, jsx_runtime_1.jsx)("pre", { children: (0, trace_utils_1.safeJsonStringify)(artifact) }, artifact.artifact_id)), artifacts.length === 0 ? (0, jsx_runtime_1.jsx)("p", { className: "muted", children: "No artifacts." }) : null] });
}
