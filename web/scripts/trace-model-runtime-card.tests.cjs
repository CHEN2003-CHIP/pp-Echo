const assert = require("assert/strict");
const fs = require("fs");
const path = require("path");
const ts = require("typescript");
const React = require("react");
const ReactDOMServer = require("react-dom/server");

const projectRoot = path.resolve(__dirname, "..");
const tempRoot = fs.mkdtempSync(path.join(projectRoot, ".trace-model-runtime-tests-"));
fs.writeFileSync(path.join(tempRoot, "package.json"), JSON.stringify({ type: "commonjs" }), "utf8");

for (const sourcePath of sourceFiles(path.join(projectRoot, "src"))) {
  compileSource(sourcePath);
}

const card = require(path.join(tempRoot, "src/features/traces/TraceModelRuntimeCard.js"));
const tests = [];

function test(name, fn) {
  tests.push({ name, fn });
}

test("extracts model runtime metadata from selected event first", () => {
  const selection = card.extractModelRuntimeSelection({
    run: { attributes: { runtime_id: "from-run" } },
    summary: { provider: "summary-provider", model: "summary-model", attributes: { runtime_id: "from-summary" } },
    events: [{
      name: "model_runtime_selected",
      payload: {
        details: {
          provider_id: "deepseek",
          model_id: "deepseek-chat",
          runtime_id: "pp_echo_native",
          model_profile_source: "configured",
          runtime_profile_source: "configured",
          model_capabilities: { tool_calling: true, vision: false },
          runtime_supports: { approval: true, checkpoint: true }
        }
      }
    }],
    spans: [],
    artifacts: [],
    diagnosis: [],
    warnings: []
  });

  assert.equal(selection.providerId, "deepseek");
  assert.equal(selection.modelId, "deepseek-chat");
  assert.equal(selection.runtimeId, "pp_echo_native");
  assert.equal(selection.modelCapabilities.tool_calling, true);
  assert.equal(selection.runtimeSupports.approval, true);
});

test("falls back to run attributes and renders empty state for old traces", () => {
  const selection = card.extractModelRuntimeSelection({
    run: { provider: "openai", model: "gpt-test", attributes: { runtime_id: "pp_echo_native", model_capabilities: { streaming: true } } },
    summary: null,
    events: [],
    spans: [],
    artifacts: [],
    diagnosis: [],
    warnings: []
  });
  assert.equal(selection.providerId, "openai");
  assert.equal(selection.modelId, "gpt-test");
  assert.equal(selection.runtimeId, "pp_echo_native");

  const html = ReactDOMServer.renderToStaticMarkup(React.createElement(card.TraceModelRuntimeCard, {
    detail: { run: null, summary: null, events: [], spans: [], artifacts: [], diagnosis: [], warnings: [] }
  }));
  assert.ok(html.includes(card.TRACE_MODEL_RUNTIME_EMPTY));
});

let failures = 0;
for (const entry of tests) {
  try {
    entry.fn();
    console.log(`ok ${entry.name}`);
  } catch (error) {
    failures += 1;
    console.error(`fail ${entry.name}`);
    console.error(error.stack || error);
  }
}

fs.rmSync(tempRoot, { recursive: true, force: true });
if (failures > 0) process.exitCode = 1;
else console.log(`Passed ${tests.length} trace model/runtime card tests.`);

function compileSource(sourcePath) {
  const absoluteSourcePath = path.join(projectRoot, sourcePath);
  const outputPath = path.join(tempRoot, sourcePath.replace(/\.(ts|tsx)$/, ".js"));
  fs.mkdirSync(path.dirname(outputPath), { recursive: true });
  const source = fs.readFileSync(absoluteSourcePath, "utf8");
  const result = ts.transpileModule(source, {
    compilerOptions: {
      module: ts.ModuleKind.CommonJS,
      target: ts.ScriptTarget.ES2020,
      jsx: ts.JsxEmit.ReactJSX,
      esModuleInterop: true,
      moduleResolution: ts.ModuleResolutionKind.NodeJs,
      sourceMap: false,
      inlineSourceMap: false,
      isolatedModules: true,
    },
    fileName: absoluteSourcePath,
  });
  fs.writeFileSync(outputPath, result.outputText, "utf8");
}

function sourceFiles(root) {
  const files = [];
  for (const entry of fs.readdirSync(root, { withFileTypes: true })) {
    const absolute = path.join(root, entry.name);
    if (entry.isDirectory()) {
      files.push(...sourceFiles(absolute));
      continue;
    }
    if (!entry.isFile() || !/\.(ts|tsx)$/.test(entry.name)) continue;
    files.push(path.relative(projectRoot, absolute).replace(/\\/g, "/"));
  }
  return files;
}
