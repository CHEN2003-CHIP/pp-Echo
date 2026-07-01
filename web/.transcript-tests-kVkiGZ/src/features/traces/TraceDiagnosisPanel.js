"use strict";
Object.defineProperty(exports, "__esModule", { value: true });
exports.TraceDiagnosisPanel = TraceDiagnosisPanel;
const jsx_runtime_1 = require("react/jsx-runtime");
function TraceDiagnosisPanel({ diagnosis, warnings }) {
    return ((0, jsx_runtime_1.jsxs)("section", { className: "trace-inspect-section", children: [(0, jsx_runtime_1.jsx)("h3", { children: "Diagnosis" }), [...diagnosis, ...warnings.map((message) => ({ code: message, severity: "warning", title: "Trace warning", message }))].map((item) => ((0, jsx_runtime_1.jsxs)("div", { className: `trace-diagnosis trace-diagnosis-${item.severity}`, children: [(0, jsx_runtime_1.jsx)("strong", { children: item.title }), (0, jsx_runtime_1.jsx)("span", { children: item.message })] }, `${item.code}-${item.message}`))), diagnosis.length === 0 && warnings.length === 0 ? (0, jsx_runtime_1.jsx)("p", { className: "muted", children: "No diagnosis." }) : null] }));
}
