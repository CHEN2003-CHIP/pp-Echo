const assert = require("assert/strict");
const fs = require("fs");
const path = require("path");
const ts = require("typescript");
const { createTempRoot } = require("./test-temp-root.cjs");

const projectRoot = path.resolve(__dirname, "..");
const tempRoot = createTempRoot("activity-presenter-tests");
fs.writeFileSync(path.join(tempRoot, "package.json"), JSON.stringify({ type: "commonjs" }), "utf8");

for (const sourcePath of [
  "src/features/activity/activity-utils.ts",
  "src/features/activity/activity-findings.ts",
  "src/features/activity/activity-types.ts",
  "src/features/activity/activity-presenter.ts",
]) {
  compileSource(sourcePath);
}

const presenter = require(path.join(tempRoot, "src/features/activity/activity-presenter.js"));
const tests = [];

function test(name, fn) {
  tests.push({ name, fn });
}

test("read_file uses the concrete file name and contextual summary", () => {
  const item = presenter.presentActivityStep({
    type: "tool_start",
    tool_name: "read_file",
    details: { path: "web/src/features/activity/ActivityCard.tsx" },
  });
  assert.ok(item.title.includes("ActivityCard.tsx"));
  assert.ok(item.body.includes("activity/reasoning"));
  assert.ok(!item.title.includes("相关文件"));
});

test("list_dir uses the concrete directory and activity organization summary", () => {
  const item = presenter.presentActivityStep({
    type: "tool_start",
    tool_name: "list_dir",
    details: { path: "web/src/features/activity" },
  });
  assert.ok(item.title.includes("web/src/features/activity"));
  assert.ok(item.body.includes("activity/reasoning"));
  assert.ok(!item.title.includes("项目结构"));
});

test("search_repo uses the query in the visible title", () => {
  const item = presenter.presentActivityStep({
    type: "tool_start",
    tool_name: "search_repo",
    details: { query: "buildTranscript" },
  });
  assert.ok(item.title.includes("buildTranscript"));
  assert.ok(item.body.includes("运行流程消息"));
});

test("run_shell explains TypeScript verification", () => {
  const item = presenter.presentActivityStep({
    type: "tool_start",
    tool_name: "run_shell",
    details: { command: "npx tsc --noEmit" },
  });
  assert.ok(item.title.includes("TypeScript"));
  assert.ok(item.body.includes("确认当前修改是否可靠"));
});

test("reasoning_delta is not treated as final private reasoning text", () => {
  const item = presenter.presentActivityStep({
    type: "reasoning_delta",
    delta: "",
    details: {},
  });
  assert.equal(item.title, "分析进展");
  assert.ok(item.body.includes("继续分析"));
});

test("presented strings do not include common mojibake fragments", () => {
  const item = presenter.presentActivityStep({
    type: "tool_start",
    tool_name: "write_file",
    details: { path: "web/src/features/activity/activity-normalizer.ts" },
  });
  const text = JSON.stringify(item);
  assert.equal(text.includes("鈥"), false);
  assert.equal(text.includes("閳"), false);
  assert.equal(text.includes("璺"), false);
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
else console.log(`Passed ${tests.length} activity presenter tests.`);

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
