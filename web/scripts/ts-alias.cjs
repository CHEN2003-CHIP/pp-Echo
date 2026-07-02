const Module = require("module");
const fs = require("fs");
const path = require("path");

const projectRoot = path.resolve(__dirname, "..");
const tempRoot = process.env.TS_ALIAS_TEMP_ROOT ? path.resolve(process.env.TS_ALIAS_TEMP_ROOT) : "";
const originalResolveFilename = Module._resolveFilename;

Module._resolveFilename = function resolveWithAlias(request, parent, isMain, options) {
  if (isStreamdownTestImport(request)) {
    return path.join(__dirname, "streamdown-test-stub.cjs");
  }
  if (request.startsWith("@/")) {
    const redirected = path.join(projectRoot, "src", request.slice(2));
    const resolved = resolveLocalModule(redirected);
    if (resolved) return resolved;
  }
  return originalResolveFilename.call(this, request, parent, isMain, options);
};

function resolveLocalModule(basePath) {
  const compiledBase = tempRoot ? path.join(tempRoot, path.relative(projectRoot, basePath)) : "";
  const candidates = [
    compiledBase,
    `${compiledBase}.js`,
    `${compiledBase}.jsx`,
    basePath,
    `${basePath}.ts`,
    `${basePath}.tsx`,
    `${basePath}.js`,
    `${basePath}.jsx`
  ].filter(Boolean);
  for (const candidate of candidates) {
    if (fs.existsSync(candidate) && fs.statSync(candidate).isFile()) return candidate;
  }
  for (const candidate of candidates) {
    if (fs.existsSync(candidate) && fs.statSync(candidate).isDirectory()) {
      for (const entry of ["index.ts", "index.tsx", "index.js", "index.jsx"]) {
        const nested = path.join(candidate, entry);
        if (fs.existsSync(nested) && fs.statSync(nested).isFile()) return nested;
      }
    }
  }
  return null;
}

function isStreamdownTestImport(request) {
  return request === "streamdown" || request === "@streamdown/cjk" || request === "@streamdown/code" || request === "@streamdown/math" || request === "@streamdown/mermaid";
}
