const assert = require("assert/strict");
const fs = require("fs");
const path = require("path");
const ts = require("typescript");
const { createTempRoot } = require("./test-temp-root.cjs");

const projectRoot = path.resolve(__dirname, "..");
const tempRoot = createTempRoot("activity-finding-tests");
fs.writeFileSync(path.join(tempRoot, "package.json"), JSON.stringify({ type: "commonjs" }), "utf8");

compileSource("src/features/activity/activity-findings.ts");

const findings = require(path.join(tempRoot, "src/features/activity/activity-findings.js"));
const tests = [];

function test(name, fn) {
  tests.push({ name, fn });
}

test("detects the activity display chain from related events", () => {
  const result = findings.buildActivityFindings([
    { type: "tool_start", tool_name: "read_file", details: { path: "web/src/App.tsx" } },
    { type: "tool_start", tool_name: "read_file", details: { path: "web/src/features/activity/ActivityCard.tsx" } },
    { type: "tool_start", tool_name: "search_repo", details: { query: "buildTranscript" } },
  ]);
  assert.ok(result.some((item) => item.id === "finding:activity-display-chain"));
  assert.ok(result.find((item) => item.id === "finding:activity-display-chain").summary.includes("ActivityCard"));
});

test("detects history reasoning restore from timeline events", () => {
  const result = findings.buildActivityFindings([
    { type: "tool_start", tool_name: "search_repo", details: { query: "timeline hydrateSession events" } },
  ]);
  assert.ok(result.some((item) => item.id === "finding:history-reasoning-restore"));
});

test("detects the board entry without requiring observer deletion", () => {
  const result = findings.buildActivityFindings([
    { type: "tool_start", tool_name: "search_repo", details: { query: 'openView("board") observer timeline' } },
  ]);
  const item = result.find((entry) => entry.id === "finding:board-entry");
  assert.ok(item);
  assert.ok(item.summary.includes("不需要深删"));
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
else console.log(`Passed ${tests.length} activity finding tests.`);

function compileSource(sourcePath) {
  const absoluteSourcePath = path.join(projectRoot, sourcePath);
  const outputPath = path.join(tempRoot, sourcePath.replace(/\.(ts|tsx)$/, ".js"));
  fs.mkdirSync(path.dirname(outputPath), { recursive: true });
  const source = fs.readFileSync(absoluteSourcePath, "utf8");
  const result = ts.transpileModule(source, {
    compilerOptions: {
      module: ts.ModuleKind.CommonJS,
      target: ts.ScriptTarget.ES2020,
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
