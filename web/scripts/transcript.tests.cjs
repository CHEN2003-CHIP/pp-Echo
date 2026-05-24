const assert = require("assert/strict");
const fs = require("fs");
const path = require("path");
const ts = require("typescript");

const projectRoot = path.resolve(__dirname, "..");
const tempRoot = fs.mkdtempSync(path.join(projectRoot, ".transcript-tests-"));
fs.writeFileSync(path.join(tempRoot, "package.json"), JSON.stringify({ type: "commonjs" }), "utf8");

for (const sourcePath of ["src/api.ts", "src/rich-text.tsx", "src/App.tsx"]) {
  compileSource(sourcePath);
}

const app = require(path.join(tempRoot, "src/App.js"));

const tests = [];
function test(name, fn) {
  tests.push({ name, fn });
}

test("buildTranscript renders tool completion as assistant feedback", () => {
  const transcript = app.buildTranscript(
    {
      messages: [
        {
          role: "user",
          content: [{ type: "text", text: "运行 test.py，看看测试结果" }],
          timestamp: 1,
        },
        {
          role: "assistant",
          content: [{ type: "text", text: "让我执行这个命令来查看测试结果。" }],
          timestamp: 2,
        },
      ],
    },
    [
      { type: "turn_start", timestamp: 3, details: { turn_id: 1 } },
      { type: "tool_start", timestamp: 4, tool_name: "run_shell", details: { tool_call_id: "call-1" } },
      {
        type: "tool_end",
        timestamp: 5,
        tool_name: "run_shell",
        message: "25\n1026",
        details: { tool_call_id: "call-1", returncode: 0 },
      },
      { type: "turn_end", timestamp: 6, details: { turn_id: 1 } },
    ],
  );

  const toolItems = transcript.filter((item) => item.role === "tool");
  const assistantItems = transcript.filter((item) => item.role === "assistant");

  assert.equal(toolItems.length, 0);
  assert.ok(assistantItems.some((item) => item.body.text.includes("执行完成")));
  assert.ok(assistantItems.some((item) => item.body.text.includes("25")));
  assert.ok(assistantItems.some((item) => item.body.text.includes("1026")));
});

test("buildTranscript renders approval results as assistant feedback", () => {
  const transcript = app.buildTranscript(
    {
      messages: [
        {
          role: "user",
          content: [{ type: "text", text: "请运行 test.py 并告诉我结果" }],
          timestamp: 1,
        },
      ],
    },
    [
      {
        type: "approval_result",
        timestamp: 2,
        message: "Command completed.\n\n25\n1026",
        details: {
          action_type: "run_shell",
          token: "token-1",
          success: true,
          result: "25\n1026",
        },
      },
    ],
  );

  const assistantItems = transcript.filter((item) => item.role === "assistant");

  assert.equal(transcript.filter((item) => item.role === "tool").length, 0);
  assert.ok(assistantItems.some((item) => item.body.text.includes("Command completed")));
  assert.ok(assistantItems.some((item) => item.body.text.includes("25")));
  assert.ok(assistantItems.some((item) => item.body.text.includes("1026")));
});

let failures = 0;
for (const entry of tests) {
  try {
    entry.fn();
    console.log(`✓ ${entry.name}`);
  } catch (error) {
    failures += 1;
    console.error(`✗ ${entry.name}`);
    console.error(error.stack || error);
  }
}

if (failures > 0) {
  process.exitCode = 1;
} else {
  console.log(`Passed ${tests.length} transcript tests.`);
}

fs.rmSync(tempRoot, { recursive: true, force: true });

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
