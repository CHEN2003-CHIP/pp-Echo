"use strict";
Object.defineProperty(exports, "__esModule", { value: true });
exports.statusLabel = void 0;
exports.statusTone = statusTone;
exports.copyText = copyText;
exports.statusLabel = {
    ok: "正常",
    warning: "注意",
    error: "阻塞",
    skipped: "跳过"
};
function statusTone(status) {
    return `onboarding-status-${status}`;
}
async function copyText(value) {
    if (!value)
        return;
    await navigator.clipboard?.writeText(value);
}
