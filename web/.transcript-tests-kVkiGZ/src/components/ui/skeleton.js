"use strict";
Object.defineProperty(exports, "__esModule", { value: true });
exports.Skeleton = Skeleton;
const jsx_runtime_1 = require("react/jsx-runtime");
const utils_1 = require("@/lib/utils");
function Skeleton({ className, ...props }) {
    return ((0, jsx_runtime_1.jsx)("div", { className: (0, utils_1.cn)("animate-pulse rounded-md bg-primary/10", className), ...props }));
}
