"use strict";
Object.defineProperty(exports, "__esModule", { value: true });
exports.StartupGuidePage = StartupGuidePage;
const jsx_runtime_1 = require("react/jsx-runtime");
const lucide_react_1 = require("lucide-react");
const react_1 = require("react");
const api_1 = require("../../api");
const StartupActionCards_1 = require("./StartupActionCards");
const StartupChecklist_1 = require("./StartupChecklist");
const StartupNextSteps_1 = require("./StartupNextSteps");
const onboarding_utils_1 = require("./onboarding-utils");
const SAFE_FIRST_TASK = "Please read README and summarize pp-Echo's core modules. Do not edit files and do not run shell commands.";
function StartupGuidePage({ onBack, onOpenTrace, onOpenChat }) {
    const [status, setStatus] = (0, react_1.useState)(null);
    const [modelCheck, setModelCheck] = (0, react_1.useState)(null);
    const [loading, setLoading] = (0, react_1.useState)(true);
    const [checkingModel, setCheckingModel] = (0, react_1.useState)(false);
    const [error, setError] = (0, react_1.useState)("");
    async function load() {
        setLoading(true);
        setError("");
        try {
            setStatus(await api_1.api.onboardingStatus());
        }
        catch (exc) {
            setError(exc instanceof Error ? exc.message : String(exc));
        }
        finally {
            setLoading(false);
        }
    }
    async function checkModel() {
        setCheckingModel(true);
        setError("");
        try {
            setModelCheck(await api_1.api.onboardingCheckModel());
        }
        catch (exc) {
            setError(exc instanceof Error ? exc.message : String(exc));
        }
        finally {
            setCheckingModel(false);
        }
    }
    (0, react_1.useEffect)(() => {
        load().catch(() => undefined);
    }, []);
    const overall = status?.overall_status || "partial";
    return ((0, jsx_runtime_1.jsxs)("section", { className: "startup-guide-page", children: [(0, jsx_runtime_1.jsxs)("header", { className: "startup-guide-hero", children: [(0, jsx_runtime_1.jsxs)("div", { children: [(0, jsx_runtime_1.jsx)("small", { children: "Startup Guide" }), (0, jsx_runtime_1.jsx)("h2", { children: "Startup Guide" }), (0, jsx_runtime_1.jsx)("p", { children: status?.workspace || "Checking the current workspace..." })] }), (0, jsx_runtime_1.jsxs)("div", { className: "startup-guide-actions", children: [(0, jsx_runtime_1.jsx)("span", { className: `startup-overall startup-overall-${overall}`, children: overall }), (0, jsx_runtime_1.jsxs)("button", { className: "startup-secondary-button", onClick: load, disabled: loading, children: [(0, jsx_runtime_1.jsx)(lucide_react_1.RefreshCw, { size: 15 }), (0, jsx_runtime_1.jsx)("span", { children: "Refresh" })] }), (0, jsx_runtime_1.jsxs)("button", { className: "startup-secondary-button", onClick: onBack, children: [(0, jsx_runtime_1.jsx)(lucide_react_1.ArrowLeft, { size: 15 }), (0, jsx_runtime_1.jsx)("span", { children: "Back to chat" })] })] })] }), error ? (0, jsx_runtime_1.jsx)("div", { className: "startup-guide-error", children: error }) : null, loading ? (0, jsx_runtime_1.jsx)("div", { className: "startup-guide-loading", children: "Checking startup environment..." }) : null, status ? (0, jsx_runtime_1.jsx)(StartupChecklist_1.StartupChecklist, { checks: modelCheck ? [...status.checks, modelCheck] : status.checks }) : null, (0, jsx_runtime_1.jsxs)("section", { className: "startup-guide-section", children: [(0, jsx_runtime_1.jsx)("div", { className: "startup-guide-section-head", children: (0, jsx_runtime_1.jsx)("h2", { children: "Model connection" }) }), (0, jsx_runtime_1.jsxs)("div", { className: "startup-model-check", children: [(0, jsx_runtime_1.jsx)("p", { children: "Clicking this runs one controlled, low-token model request. Startup checks do not run it automatically." }), (0, jsx_runtime_1.jsxs)("button", { onClick: checkModel, disabled: checkingModel, children: [(0, jsx_runtime_1.jsx)(lucide_react_1.Wifi, { size: 15 }), (0, jsx_runtime_1.jsx)("span", { children: checkingModel ? "Checking" : "Test model connection" })] }), (0, jsx_runtime_1.jsx)("small", { children: "API keys are read from environment variables and are never returned to the page." }), modelCheck ? ((0, jsx_runtime_1.jsxs)("div", { className: `startup-model-result ${(0, onboarding_utils_1.statusTone)(modelCheck.status)}`, children: [(0, jsx_runtime_1.jsxs)("strong", { children: [onboarding_utils_1.statusLabel[modelCheck.status], ": ", modelCheck.summary] }), modelCheck.detail ? (0, jsx_runtime_1.jsx)("span", { children: modelCheck.detail }) : null] })) : null] })] }), status ? (0, jsx_runtime_1.jsx)(StartupActionCards_1.StartupActionCards, { status: status, onOpenTrace: onOpenTrace }) : null, (0, jsx_runtime_1.jsxs)("section", { className: "startup-guide-section", children: [(0, jsx_runtime_1.jsx)("div", { className: "startup-guide-section-head", children: (0, jsx_runtime_1.jsx)("h2", { children: "Safe first task" }) }), (0, jsx_runtime_1.jsxs)("div", { className: "startup-safe-task", children: [(0, jsx_runtime_1.jsx)("p", { children: SAFE_FIRST_TASK }), (0, jsx_runtime_1.jsxs)("button", { onClick: () => (0, onboarding_utils_1.copyText)(SAFE_FIRST_TASK), children: [(0, jsx_runtime_1.jsx)(lucide_react_1.Copy, { size: 14 }), (0, jsx_runtime_1.jsx)("span", { children: "Copy prompt" })] })] })] }), (0, jsx_runtime_1.jsx)(StartupNextSteps_1.StartupNextSteps, { status: status, onOpenChat: onOpenChat, onOpenTrace: onOpenTrace })] }));
}
