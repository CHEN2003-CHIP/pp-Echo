const assert = require("assert/strict");
const fs = require("fs");
const path = require("path");
const ts = require("typescript");

const projectRoot = path.resolve(__dirname, "..");
const tempRoot = fs.mkdtempSync(path.join(projectRoot, ".transcript-tests-"));
fs.writeFileSync(path.join(tempRoot, "package.json"), JSON.stringify({ type: "commonjs" }), "utf8");

for (const sourcePath of sourceFiles(path.join(projectRoot, "src"))) {
  compileSource(sourcePath);
}

const app = require(path.join(tempRoot, "src/App.js"));

const tests = [];
function test(name, fn) {
  tests.push({ name, fn });
}

test("buildTranscript renders tool completion as collapsed activity", () => {
  const transcript = app.buildTranscript(
    {
      messages: [
        {
          role: "user",
          content: [{ type: "text", text: "Run test.py and show the result" }],
          timestamp: 1,
        },
        {
          role: "assistant",
          content: [{ type: "text", text: "I will run the command." }],
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
  const activityItems = transcript.filter((item) => item.role === "activity");
  const assistantItems = transcript.filter((item) => item.role === "assistant");

  assert.equal(toolItems.length, 0);
  assert.equal(activityItems.length, 1);
  assert.ok(activityItems[0].activity.title.includes("已处理"));
  assert.ok(activityItems[0].activity.title.includes("3s"));
  assert.ok(activityItems[0].activity.summary.includes("已运行 1 条命令"));
  assert.ok(activityItems[0].activity.entries.some((entry) => entry.label === "run_shell"));
  assert.ok(activityItems[0].activity.entries.some((entry) => entry.durationLabel === "1s"));
  assert.ok(activityItems.some((item) => item.body.text.includes("25")));
  assert.ok(activityItems.some((item) => item.body.text.includes("1026")));
  assert.equal(assistantItems.some((item) => item.body.text.includes("25")), false);
});

test("buildTranscript groups multiple tools in one turn", () => {
  const transcript = app.buildTranscript(
    { messages: [] },
    [
      { type: "local_user_prompt", timestamp: 1, message: "search and fetch" },
      { type: "tool_start", timestamp: 2, tool_name: "web.news", details: { tool_call_id: "news-1" } },
      { type: "tool_end", timestamp: 4, tool_name: "web.news", message: "News result", details: { tool_call_id: "news-1" } },
      { type: "tool_start", timestamp: 5, tool_name: "web.fetch", details: { tool_call_id: "fetch-1" } },
      { type: "tool_result", timestamp: 7, tool_name: "web.fetch", message: "Fetched page", details: { tool_call_id: "fetch-1" } },
      { type: "turn_end", timestamp: 8 },
    ],
  );

  const activityItems = transcript.filter((item) => item.role === "activity");
  assert.equal(activityItems.length, 1);
  assert.ok(activityItems[0].activity.title.includes("已处理"));
  assert.ok(activityItems[0].activity.summary.includes("已调用 2 个工具"));
  assert.deepEqual(activityItems[0].activity.entries.map((entry) => entry.label), ["web.news", "web.fetch"]);
  assert.ok(activityItems[0].body.text.includes("News result"));
  assert.ok(activityItems[0].body.text.includes("Fetched page"));
});

test("buildTranscript keeps process narration as assistant text", () => {
  const transcript = app.buildTranscript(
    {
      messages: [
        { role: "user", content: [{ type: "text", text: "Update the UI" }], timestamp: 1 },
        { role: "assistant", content: [{ type: "text", text: "Finished the UI update." }], timestamp: 9 },
      ],
    },
    [
      { type: "turn_start", timestamp: 2 },
      { type: "message_delta", timestamp: 3, delta: "我先确认当前工作树，避免覆盖已有改动。" },
      { type: "tool_start", timestamp: 4, tool_name: "run_shell", details: { tool_call_id: "status", command: "git status --short" } },
      { type: "tool_end", timestamp: 5, tool_name: "run_shell", message: "", details: { tool_call_id: "status", command: "git status --short", returncode: 0 } },
      { type: "turn_end", timestamp: 8 },
    ],
  );

  const activity = transcript.find((item) => item.role === "activity");
  assert.ok(activity);
  assert.equal(activity.activity.entries.some((entry) => entry.kind === "narrative"), false);
  assert.ok(activity.activity.entries.some((entry) => entry.label === "run_shell"));
  assert.ok(transcript.some((item) => item.role === "assistant" && item.body.text.includes("Finished the UI update.")));
  assert.ok(transcript.some((item) => item.role === "assistant" && item.body.text.includes("确认当前工作树")));
});

test("buildTranscript keeps planner nodes and adds planner details", () => {
  const transcript = app.buildTranscript(
    { messages: [] },
    [
      { type: "turn_start", timestamp: 1 },
      { type: "planner_start", timestamp: 2 },
      {
        type: "planner_end",
        timestamp: 3,
        details: {
          summary: ["Edit web/src/App.tsx [edit_file]", "Run npm test [run_shell]"],
          files_touched_guess: ["web/src/App.tsx"],
          shell_commands_guess: ["npm test"],
          tools: ["edit_file", "run_shell"],
          step_count: 2,
        },
      },
      { type: "turn_end", timestamp: 4 },
    ],
  );

  const activity = transcript.find((item) => item.role === "activity");
  assert.ok(activity);
  const plannerStart = activity.activity.entries.find((entry) => entry.label === "planner_start");
  const plannerEnd = activity.activity.entries.find((entry) => entry.label === "planner_end");
  assert.ok(plannerStart);
  assert.ok(plannerEnd);
  assert.ok(plannerStart.detail.includes("计划包含 2 个步骤"));
  assert.ok(activity.body.text.includes("计划包含 2 个步骤"));
  assert.ok(activity.body.text.includes("预计处理文件：web/src/App.tsx"));
  assert.ok(activity.body.text.includes("准备运行命令：npm test"));
  assert.equal(activity.body.text.includes("Updated"), false);
});

test("buildTranscript updates running tool activity when the tool completes", () => {
  const runningTranscript = app.buildTranscript(
    { messages: [] },
    [
      { type: "turn_start", timestamp: 1 },
      { type: "tool_start", timestamp: 2, tool_name: "run_shell", details: { tool_call_id: "shell-1", command: "npm test" } },
    ],
  );
  const runningActivity = runningTranscript.find((item) => item.role === "activity");
  assert.ok(runningActivity);
  assert.ok(runningActivity.activity.title.includes("处理中"));
  assert.equal(runningActivity.activity.running, true);
  assert.equal(runningActivity.activity.entries[0].tone, "running");

  const completedTranscript = app.buildTranscript(
    { messages: [] },
    [
      { type: "turn_start", timestamp: 1 },
      { type: "tool_start", timestamp: 2, tool_name: "run_shell", details: { tool_call_id: "shell-1", command: "npm test" } },
      { type: "tool_end", timestamp: 5, tool_name: "run_shell", message: "ok", details: { tool_call_id: "shell-1", command: "npm test", returncode: 0 } },
      { type: "turn_end", timestamp: 6 },
    ],
  );
  const completedActivity = completedTranscript.find((item) => item.role === "activity");
  assert.ok(completedActivity);
  assert.ok(completedActivity.activity.title.includes("已处理"));
  assert.equal(completedActivity.activity.running, false);
  assert.equal(completedActivity.activity.entries[0].durationLabel, "3s");
});

test("buildTranscript attaches safe web result images to tool activity", () => {
  const transcript = app.buildTranscript(
    { messages: [] },
    [
      {
        type: "tool_end",
        timestamp: 1,
        tool_name: "web.news",
        message: "News result",
        details: {
          tool_call_id: "call-images",
          results: [
            { title: "A", url: "https://example.com/a", image_url: "https://example.com/a.png" },
            { title: "B", url: "https://example.com/b", image_url: "javascript:alert(1)" },
            { title: "C", url: "https://example.com/c", thumbnail: "https://example.com/c.png" },
            { title: "Logo", url: "https://example.com/logo", image_url: "https://example.com/logo.png" },
          ],
        },
      },
    ],
  );

  const activity = transcript.find((item) => item.role === "activity");
  assert.ok(activity);
  assert.equal(activity.body.attachments.length, 2);
  assert.equal(activity.body.attachments[0].url, "https://example.com/a.png");
  assert.equal(activity.body.attachments[1].url, "https://example.com/c.png");
});

test("buildTranscript attaches fetched page images to tool activity", () => {
  const transcript = app.buildTranscript(
    { messages: [] },
    [
      {
        type: "tool_end",
        timestamp: 1,
        tool_name: "web.fetch",
        message: "Fetched article",
        details: {
          tool_call_id: "call-fetch-images",
          images: [
            { url: "https://example.com/hero.png", title: "Hero" },
            { url: "file:///secret.png", title: "Blocked" },
          ],
        },
      },
    ],
  );

  const activity = transcript.find((item) => item.role === "activity");
  assert.ok(activity);
  assert.equal(activity.body.attachments.length, 1);
  assert.equal(activity.body.attachments[0].url, "https://example.com/hero.png");
});

test("buildTranscript renders approval results as assistant feedback", () => {
  const transcript = app.buildTranscript(
    {
      messages: [
        {
          role: "user",
          content: [{ type: "text", text: "Please run test.py and tell me the result" }],
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
  const activityItems = transcript.filter((item) => item.role === "activity");

  assert.equal(transcript.filter((item) => item.role === "tool").length, 0);
  assert.equal(assistantItems.some((item) => item.body.text.includes("Command completed")), false);
  assert.equal(activityItems.length, 1);
  assert.ok(activityItems[0].activity.entries.some((entry) => entry.kind === "approval"));
  assert.ok(activityItems[0].body.text.includes("Command completed"));
  assert.ok(activityItems[0].body.text.includes("25"));
  assert.ok(activityItems[0].body.text.includes("1026"));
});

test("buildTranscript marks failed tool activity", () => {
  const transcript = app.buildTranscript(
    { messages: [] },
    [
      { type: "turn_start", timestamp: 1 },
      { type: "tool_start", timestamp: 2, tool_name: "run_shell", details: { tool_call_id: "bad", command: "exit 1" } },
      { type: "tool_error", timestamp: 3, tool_name: "run_shell", message: "failed", is_error: true, details: { tool_call_id: "bad", command: "exit 1" } },
    ],
  );

  const activity = transcript.find((item) => item.role === "activity");
  assert.ok(activity);
  assert.ok(activity.activity.title.includes("处理失败"));
  assert.equal(activity.activity.tone, "error");
  assert.equal(activity.activity.entries[0].tone, "error");
});

test("buildTurnMarkers groups transcript by user turns", () => {
  const markers = app.buildTurnMarkers([
    { id: "u1", role: "user", body: { text: "First question", attachments: [] } },
    { id: "a1", role: "assistant", body: { text: "First answer", attachments: [] } },
    { id: "u2", role: "user", body: { text: "Second question", attachments: [] } },
    { id: "act1", role: "activity", body: { text: "Tool output", attachments: [] }, activity: { title: "Done", summary: "ran tests", detail: "ok" } },
    { id: "a2", role: "assistant", body: { text: "Second answer", attachments: [] } },
  ]);

  assert.equal(markers.length, 2);
  assert.equal(markers[0].id, "u1");
  assert.equal(markers[0].turnNumber, 1);
  assert.equal(markers[0].userPreview, "First question");
  assert.equal(markers[0].assistantPreview, "First answer");
  assert.equal(markers[1].id, "u2");
  assert.equal(markers[1].turnNumber, 2);
  assert.ok(markers[1].assistantPreview.includes("ran tests"));
  assert.ok(markers[1].assistantPreview.includes("Second answer"));
});

test("buildTurnMarkers handles empty and single-turn transcripts", () => {
  assert.deepEqual(app.buildTurnMarkers([]), []);

  const markers = app.buildTurnMarkers([
    { id: "intro", role: "assistant", body: { text: "Hello", attachments: [] } },
    { id: "u1", role: "user", body: { text: "Only turn", attachments: [] } },
  ]);

  assert.equal(markers.length, 1);
  assert.equal(markers[0].userPreview, "Only turn");
  assert.equal(markers[0].assistantPreview, "");
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

function sourceFiles(root) {
  const files = [];
  for (const entry of fs.readdirSync(root, { withFileTypes: true })) {
    const absolute = path.join(root, entry.name);
    if (entry.isDirectory()) {
      files.push(...sourceFiles(absolute));
      continue;
    }
    if (!entry.isFile() || !/\.(ts|tsx)$/.test(entry.name)) {
      continue;
    }
    files.push(path.relative(projectRoot, absolute).replace(/\\/g, "/"));
  }
  return files;
}
