const assert = require("assert/strict");
const fs = require("fs");
const path = require("path");
const ts = require("typescript");
const { createTempRoot } = require("./test-temp-root.cjs");

const projectRoot = path.resolve(__dirname, "..");
const tempRoot = createTempRoot("context-summary-tests");
fs.writeFileSync(path.join(tempRoot, "package.json"), JSON.stringify({ type: "commonjs" }), "utf8");
process.env.TS_ALIAS_TEMP_ROOT = tempRoot;
require("./ts-alias.cjs");

for (const sourcePath of sourceFiles(path.join(projectRoot, "src"))) {
  compileSource(sourcePath);
}

const app = require(path.join(tempRoot, "src/App.js"));

const tests = [];
function test(name, fn) {
  tests.push({ name, fn });
}

test("buildContextSummary does not fake a pipeline budget before context is built", () => {
  const summary = app.buildContextSummary(
    {
      history: { source: "stored", visible_message_count: 4, returned_message_count: 4, max_total_text_chars: 80000 },
      messages: [{ role: "user", content: [{ type: "text", text: "hello" }], timestamp: 1 }],
    },
    [],
    "gpt-4o",
  );

  assert.equal(summary.modelContextUsage.totalLabel, "128K");
  assert.equal(summary.modelContextUsage.source, "estimated");
  assert.equal(summary.pipelineBudgetUsage.source, "unavailable");
  assert.equal(summary.pipelineBudgetUsage.isAvailable, false);
  assert.notEqual(summary.pipelineBudgetUsage.totalLabel, "80K");
  assert.equal(summary.pipelineBudgetUsage.totalChars, undefined);
  assert.equal(summary.pipelineBudgetUsage.percent, undefined);
});

test("buildContextSummary uses actual context_built report for pipeline budget", () => {
  const summary = app.buildContextSummary(
    { messages: [] },
    [
      {
        type: "context_built",
        timestamp: 1,
        details: {
          context_window_tokens: 128000,
          context: {
            budget_report: {
              total_budget: 30900,
              used: 16100,
              dropped_items: [{ id: "old", reason: "total_budget_exceeded" }],
            },
          },
        },
      },
    ],
    "gpt-4o",
  );

  assert.equal(summary.modelContextUsage.totalLabel, "128K");
  assert.equal(summary.pipelineBudgetUsage.source, "actual");
  assert.equal(summary.pipelineBudgetUsage.totalLabel, "31K");
  assert.equal(summary.pipelineBudgetUsage.usedLabel, "16K");
  assert.ok(Math.abs(summary.pipelineBudgetUsage.percent - 0.521) < 0.01);
  assert.equal(summary.pipelineBudgetUsage.truncated, true);
});

test("buildContextSummary keeps model context and pipeline budget independent", () => {
  const summary = app.buildContextSummary(
    { messages: [] },
    [
      {
        type: "provider_response",
        timestamp: 1,
        details: { input_tokens: 11000, context_window_tokens: 128000 },
      },
      {
        type: "context_built",
        timestamp: 2,
        details: { context: { budget_report: { total_budget: 30900, used: 16100 } } },
      },
    ],
    "gpt-4o",
  );

  assert.equal(summary.modelContextUsage.totalLabel, "128K");
  assert.equal(summary.pipelineBudgetUsage.totalLabel, "31K");
  assert.equal(summary.modelContextUsage.totalTokens, 128000);
  assert.equal(summary.pipelineBudgetUsage.totalChars, 30900);
});

test("buildContextSummary can show configured pipeline budget without estimated progress", () => {
  const summary = app.buildContextSummary(
    { context_pipeline: { total_budget: 30900 }, messages: [] },
    [],
    "gpt-4o",
  );

  assert.equal(summary.pipelineBudgetUsage.source, "configured");
  assert.equal(summary.pipelineBudgetUsage.totalLabel, "31K");
  assert.equal(summary.pipelineBudgetUsage.percent, undefined);
  assert.equal(summary.pipelineBudgetUsage.percentLabel, "Not built yet");
  assert.equal(summary.pipelineBudgetUsage.isAvailable, true);
});

test("buildContextSummary restores actual pipeline budget from timeline context_built event", () => {
  const event = app.timelineEntryToRuntimeEvent({
    id: "tl-context",
    session_id: "session-1",
    created_at: 1,
    event_type: "runtime_event",
    details: {
      type: "context_built",
      context: { budget_report: { total_budget: 30900, used: 16100 } },
    },
  });
  const summary = app.buildContextSummary({ history: { source: "stored" }, messages: [] }, [event], "gpt-4o");

  assert.equal(summary.pipelineBudgetUsage.source, "actual");
  assert.equal(summary.pipelineBudgetUsage.totalLabel, "31K");
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

if (failures > 0) process.exitCode = 1;
else console.log(`Passed ${tests.length} context summary tests.`);

fs.rmSync(tempRoot, { recursive: true, force: true });

function compileSource(sourcePath) {
  const absoluteSourcePath = path.join(projectRoot, sourcePath);
  const outputPath = path.join(tempRoot, sourcePath.replace(/\.(ts|tsx)$/, ".js"));
  fs.mkdirSync(path.dirname(outputPath), { recursive: true });
  const source = fs.readFileSync(absoluteSourcePath, "utf8").replace(/\bimport\.meta\.env\b/g, "{}");
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
    if (!entry.isFile() || entry.name.endsWith(".d.ts") || !/\.(ts|tsx)$/.test(entry.name)) continue;
    files.push(path.relative(projectRoot, absolute).replace(/\\/g, "/"));
  }
  return files;
}
