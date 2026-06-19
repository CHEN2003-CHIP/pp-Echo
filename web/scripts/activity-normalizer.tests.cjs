const assert = require("assert/strict");
const fs = require("fs");
const path = require("path");
const ts = require("typescript");

const projectRoot = path.resolve(__dirname, "..");
const tempRoot = fs.mkdtempSync(path.join(projectRoot, ".activity-tests-"));
fs.writeFileSync(path.join(tempRoot, "package.json"), JSON.stringify({ type: "commonjs" }), "utf8");

for (const sourcePath of sourceFiles(path.join(projectRoot, "src"))) {
  compileSource(sourcePath);
}

const normalizer = require(path.join(tempRoot, "src/features/activity/activity-normalizer.js"));
const utils = require(path.join(tempRoot, "src/features/activity/activity-utils.js"));
const tests = [];

function test(name, fn) {
  tests.push({ name, fn });
}

test("merges public progress into one running activity", () => {
  const items = normalizer.buildActivityRuns([
    { type: "reasoning_start", timestamp: 1, run_id: "run-1", turn_id: 1, details: { summary: "Preparing context" } },
    { type: "reasoning_delta", timestamp: 2, run_id: "run-1", turn_id: 1, delta: "Receiving public assistant output.", details: { summary: "Streaming" } },
  ]);
  assert.equal(items.length, 1);
  assert.equal(items[0].phase, "preparing");
  assert.equal(items[0].status, "running");
  assert.equal(items[0].entries.length, 2);
  assert.ok(!JSON.stringify(items[0]).includes("Thinking"));
  assert.ok(!JSON.stringify(items[0]).includes("Reasoning"));
});

test("pairs tool start and end by activity id fallback", () => {
  const items = normalizer.buildActivityRuns([
    { type: "tool_start", timestamp: 2, run_id: "run-1", tool_name: "run_shell", details: { tool_call_id: "call-1", command: "npm test" } },
    { type: "tool_end", timestamp: 5, run_id: "run-1", tool_name: "run_shell", message: "ok", details: { tool_call_id: "call-1", command: "npm test", returncode: 0 } },
  ]);
  assert.equal(items.length, 1);
  assert.equal(items[0].phase, "tool");
  assert.equal(items[0].status, "success");
  assert.equal(items[0].toolCount, 1);
  assert.ok(items[0].detail.includes("Command: npm test"));
  assert.ok(items[0].detail.includes("Exit: 0"));
});

test("marks failed tools and keeps output preview", () => {
  const items = normalizer.buildActivityRuns([
    { type: "tool_start", timestamp: 2, run_id: "run-1", tool_name: "run_shell", details: { tool_call_id: "bad", command: "exit 1" } },
    { type: "tool_error", timestamp: 3, run_id: "run-1", tool_name: "run_shell", message: "failed", is_error: true, details: { tool_call_id: "bad", command: "exit 1" } },
  ]);
  assert.equal(items.length, 1);
  assert.equal(items[0].status, "error");
  assert.equal(items[0].errorCount, 1);
  assert.ok(items[0].summary.includes("failed"));
});

test("maps planner approval gate as approval activity", () => {
  const items = normalizer.buildActivityRuns([
    { type: "planner_gate_pending", timestamp: 1, run_id: "run-1", details: { token: "tok-1", summary: ["Edit file"], requires_approval: true } },
  ]);
  assert.equal(items.length, 1);
  assert.equal(items[0].phase, "approval");
  assert.equal(items[0].status, "pending");
  assert.equal(items[0].approvalCount, 1);
});

test("maps subagent checkpoint and system events", () => {
  const items = normalizer.buildActivityRuns([
    { type: "subagent_start", timestamp: 1, run_id: "run-1", details: { spec_name: "reviewer", child_session_id: "child-1" } },
    { type: "subagent_end", timestamp: 3, run_id: "run-1", details: { spec_name: "reviewer", child_session_id: "child-1", summary: "done" } },
    { type: "checkpoint_created", timestamp: 4, run_id: "run-1", details: { checkpoint_id: "cp-1", changed_paths: ["a.py"] } },
    { type: "queue_update", timestamp: 5, run_id: "run-1", details: { delivery: "follow_up" } },
  ]);
  assert.equal(items.length, 3);
  assert.ok(items.some((item) => item.phase === "subagent" && item.status === "success"));
  assert.ok(items.some((item) => item.phase === "checkpoint"));
  assert.ok(items.some((item) => item.phase === "queue"));
});

test("deduplicates explicit event ids", () => {
  const items = normalizer.buildActivityRuns([
    { type: "tool_start", event_id: "evt-1", timestamp: 1, run_id: "run-1", tool_name: "read_file", details: { tool_call_id: "call-1" } },
    { type: "tool_start", event_id: "evt-1", timestamp: 1, run_id: "run-1", tool_name: "read_file", details: { tool_call_id: "call-1" } },
  ]);
  assert.equal(items.length, 1);
  assert.equal(items[0].eventCount, 1);
});

test("safe raw event redacts private fields and trims long payloads", () => {
  const raw = utils.safeRawEvent({
    type: "reasoning_summary",
    details: {
      reasoning: "private",
      system_prompt: "do not show",
      nested: { scratchpad: "hidden", output: "x".repeat(2000) }
    }
  });
  assert.ok(raw.includes("[redacted]"));
  assert.ok(!raw.includes("do not show"));
  assert.ok(!raw.includes("hidden"));
  assert.ok(raw.length <= 4000);
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
else console.log(`Passed ${tests.length} activity normalizer tests.`);

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
