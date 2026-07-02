const assert = require("assert/strict");
const fs = require("fs");
const path = require("path");
const ts = require("typescript");

const projectRoot = path.resolve(__dirname, "..");
const tempRoot = fs.mkdtempSync(path.join(projectRoot, ".transcript-tests-"));
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

test("buildTranscript renders tool completion as collapsed activity", () => {
  const transcript = app.buildTranscript(
    {
      messages: [
        { role: "user", content: [{ type: "text", text: "Run test.py and show the result" }], timestamp: 1 },
        { role: "assistant", content: [{ type: "text", text: "I will run the command." }], timestamp: 2 },
      ],
    },
    [
      { type: "turn_start", timestamp: 3, details: { turn_id: 1 } },
      { type: "tool_start", timestamp: 4, tool_name: "run_shell", details: { tool_call_id: "call-1" } },
      { type: "tool_end", timestamp: 5, tool_name: "run_shell", message: "25\n1026", details: { tool_call_id: "call-1", returncode: 0 } },
      { type: "turn_end", timestamp: 6, details: { turn_id: 1 } },
    ],
  );

  const activityItems = transcript.filter((item) => item.role === "activity");
  assert.equal(activityItems.length, 1);
  assert.equal(transcript.filter((item) => item.role === "tool").length, 0);
  assert.ok(activityItems[0].activity.title.length > 0);
  assert.ok(activityItems[0].activity.summary.length > 0);
  assert.ok(activityItems[0].activity.entries.some((entry) => entry.label.length > 0));
  assert.ok(activityItems[0].activity.entries.some((entry) => entry.durationLabel === "1s"));
  assert.ok(activityItems[0].body.text.includes("25"));
  assert.ok(activityItems[0].body.text.includes("1026"));
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
  assert.ok(activityItems[0].activity.entries.length >= 2);
  const labels = Array.from(new Set(activityItems[0].activity.entries.map((entry) => entry.label)));
  assert.ok(labels.some((label) => label.includes("查找") || label.includes("搜索")));
  assert.ok(labels.some((label) => label.includes("读取网页")));
  assert.ok(activityItems[0].body.text.includes("News result"));
  assert.ok(activityItems[0].body.text.includes("Fetched page"));
});

test("buildTranscript restores activity from timeline-derived runtime events", () => {
  const timeline = [
    {
      id: "tl-1",
      session_id: "session-1",
      created_at: 2,
      event_type: "reasoning_summary",
      turn_id: 1,
      message: "我已经确认历史 reasoning 的恢复方向。",
      details: { summary: "我已经确认历史 reasoning 的恢复方向。" },
    },
    {
      id: "tl-2",
      session_id: "session-1",
      created_at: 3,
      event_type: "tool_start",
      turn_id: 1,
      tool_name: "search_repo",
      details: { query: "timeline hydrateSession events", tool_call_id: "call-1" },
    },
  ];
  const events = timeline.map(app.timelineEntryToRuntimeEvent);
  const transcript = app.buildTranscript(
    {
      history: { source: "stored" },
      messages: [
        { role: "user", content: [{ type: "text", text: "Show history" }], timestamp: 1 },
        { role: "assistant", content: [{ type: "text", text: "Done" }], timestamp: 9 },
      ],
    },
    events,
  );
  const activity = transcript.find((item) => item.role === "activity");
  assert.ok(activity);
  assert.ok(activity.activity.summary.includes("timeline") || activity.activity.summary.includes("历史"));
  assert.equal(events[0].type, "reasoning_summary");
  assert.equal(events[0].timestamp, 2);
});

test("timelineEntryToRuntimeEvent unwraps embedded runtime events and merge dedupes timeline/live events", () => {
  const timelineEvent = app.timelineEntryToRuntimeEvent({
    id: "tl-embedded-tool",
    session_id: "session-1",
    created_at: "2026-07-02T00:00:03Z",
    event_type: "runtime_event",
    details: JSON.stringify({
      runtime_event: {
        type: "tool_start",
        tool_name: "read_file",
        details: { path: "web/src/App.tsx", tool_call_id: "call-read" },
      },
    }),
  });
  assert.equal(timelineEvent.type, "tool_start");
  assert.equal(timelineEvent.tool_name, "read_file");
  assert.equal(timelineEvent.details.path, "web/src/App.tsx");
  assert.equal(timelineEvent.details.timeline_id, "tl-embedded-tool");
  assert.ok(timelineEvent.timestamp > 0);

  const merged = app.mergeRuntimeEvents(
    [{ ...timelineEvent, message: "live copy" }],
    [timelineEvent],
  );
  assert.equal(merged.length, 1);
  assert.equal(merged[0].message, "live copy");
});

test("buildTranscript restores runtime_event details from stored timeline entries", () => {
  const events = [
    app.timelineEntryToRuntimeEvent({
      id: "tl-reasoning",
      session_id: "session-1",
      created_at: 2,
      event_type: "runtime_event",
      details: {
        type: "reasoning_summary",
        message: "Confirmed the stored timeline can restore public reasoning summary.",
        summary: "Confirmed the stored timeline can restore public reasoning summary.",
      },
    }),
    app.timelineEntryToRuntimeEvent({
      id: "tl-tool",
      session_id: "session-1",
      created_at: 3,
      event_type: "runtime_event",
      details: {
        type: "tool_start",
        tool_name: "search_repo",
        details: { query: "timeline hydrateSession events", tool_call_id: "call-1" },
      },
    }),
  ];
  const transcript = app.buildTranscript(
    {
      history: { source: "stored" },
      messages: [{ role: "user", content: [{ type: "text", text: "Show history" }], timestamp: 1 }],
    },
    events,
  );
  const activity = transcript.find((item) => item.role === "activity");
  assert.ok(activity);
  assert.ok(activity.activity.summary.includes("timeline") || activity.body.text.includes("timeline"));
  assert.equal(events[0].type, "reasoning_summary");
  assert.equal(events[1].type, "tool_start");
  assert.equal(events[1].tool_name, "search_repo");
  assert.equal(events[1].details.query, "timeline hydrateSession events");
});

test("buildTranscript falls back to messages-only when restored timeline is empty", () => {
  const transcript = app.buildTranscript(
    {
      history: { source: "stored" },
      messages: [
        { role: "user", content: [{ type: "text", text: "Show history" }], timestamp: 1 },
        { role: "assistant", content: [{ type: "text", text: "Messages still render" }], timestamp: 2 },
      ],
    },
    [],
  );
  assert.equal(transcript.length, 2);
  assert.equal(transcript.some((item) => item.role === "activity"), false);
  assert.ok(transcript.some((item) => item.body.text.includes("Messages still render")));
});

test("buildTranscript uses persisted activity blocks before assistant final message", () => {
  const transcript = app.buildTranscript(
    {
      messages: [
        { role: "user", content: [{ type: "text", text: "Show history" }], timestamp: 1 },
        { role: "assistant", content: [{ type: "text", text: "Done" }], timestamp: 4 },
      ],
      activity_blocks: [
        {
          record_type: "activity_block",
          version: 1,
          id: "block-1",
          session_id: "session-1",
          turn_id: "1",
          created_at: 3,
          status: "done",
          title: "分析进展",
          summary: "Public summary",
          duration_ms: 2000,
          event_count: 2,
          source_event_ids: ["evt-1", "evt-2"],
          items: [
            { kind: "progress", title: "整理结论", summary: "Public summary", detail: "safe display detail", status: "success", timestamp: 2 },
          ],
        },
      ],
    },
    [],
  );

  const roles = transcript.map((item) => item.role);
  assert.deepEqual(roles, ["user", "activity", "assistant"]);
  const activity = transcript.find((item) => item.role === "activity");
  assert.ok(activity);
  assert.equal(activity.activity.title, "分析进展");
  assert.equal(activity.activity.summary, "Public summary");
  assert.equal(activity.activity.running, false);
});

test("buildTranscript keeps late persisted activity block before same-turn assistant", () => {
  const transcript = app.buildTranscript(
    {
      messages: [
        { role: "user", content: [{ type: "text", text: "Question" }], timestamp: 1000 },
        { role: "assistant", content: [{ type: "text", text: "Final answer" }], timestamp: 2000, metadata: { turn_id: "t1" } },
      ],
      activity_blocks: [
        {
          record_type: "activity_block",
          version: 1,
          id: "block-late",
          session_id: "session-1",
          turn_id: "t1",
          created_at: 3000,
          status: "done",
          title: "Analysis progress",
          summary: "Late but same turn",
          event_count: 1,
          source_event_ids: ["e1"],
          items: [{ kind: "progress", title: "Analyzed", summary: "Late but same turn", status: "success", timestamp: 2500 }],
        },
      ],
    },
    [],
  );

  assert.deepEqual(transcript.map((item) => item.role), ["user", "activity", "assistant"]);
  assert.ok(transcript.findIndex((item) => item.role === "activity") < transcript.findIndex((item) => item.role === "assistant"));
});

test("buildTranscript places runtime fallback activity before assistant even when turn_end is late", () => {
  const transcript = app.buildTranscript(
    {
      messages: [
        { role: "user", content: [{ type: "text", text: "Question" }], timestamp: 1000 },
        { role: "assistant", content: [{ type: "text", text: "Final answer" }], timestamp: 2000, metadata: { turn_id: "t1" } },
      ],
    },
    [
      { type: "context_built", timestamp: 1200, turn_id: 1, details: { turn_id: "t1" } },
      { type: "provider_response", timestamp: 1800, turn_id: 1, details: { turn_id: "t1" } },
      { type: "turn_end", timestamp: 3000, turn_id: 1, details: { turn_id: "t1" } },
    ],
  );

  assert.deepEqual(transcript.map((item) => item.role), ["user", "activity", "assistant"]);
});

test("buildTranscript inserts orphan activity before nearest assistant when assistant lacks turn id", () => {
  const transcript = app.buildTranscript(
    {
      messages: [
        { role: "user", content: [{ type: "text", text: "Question" }], timestamp: 1000 },
        { role: "assistant", content: [{ type: "text", text: "Final answer" }], timestamp: 2000 },
      ],
      activity_blocks: [
        {
          record_type: "activity_block",
          version: 1,
          id: "block-orphan",
          session_id: "session-1",
          turn_id: "missing-turn",
          created_at: 3000,
          status: "done",
          title: "Analysis progress",
          summary: "Orphan block",
          event_count: 1,
          source_event_ids: ["e1"],
          items: [{ kind: "progress", title: "Analyzed", summary: "Orphan block", status: "success", timestamp: 2500 }],
        },
      ],
    },
    [],
  );

  assert.deepEqual(transcript.map((item) => item.role), ["user", "activity", "assistant"]);
});

test("buildTranscript keeps multi-turn activity before each assistant", () => {
  const transcript = app.buildTranscript(
    {
      messages: [
        { role: "user", content: [{ type: "text", text: "Q1" }], timestamp: 1000 },
        { role: "assistant", content: [{ type: "text", text: "A1" }], timestamp: 2000 },
        { role: "user", content: [{ type: "text", text: "Q2" }], timestamp: 4000 },
        { role: "assistant", content: [{ type: "text", text: "A2" }], timestamp: 5000 },
      ],
      activity_blocks: [
        { record_type: "activity_block", version: 1, id: "b1", session_id: "s", turn_id: "1", created_at: 3000, status: "done", title: "T1", summary: "S1", event_count: 1, source_event_ids: ["e1"], items: [] },
        { record_type: "activity_block", version: 1, id: "b2", session_id: "s", turn_id: "2", created_at: 6000, status: "done", title: "T2", summary: "S2", event_count: 1, source_event_ids: ["e2"], items: [] },
      ],
    },
    [],
  );

  assert.deepEqual(transcript.map((item) => item.role), ["user", "activity", "assistant", "user", "activity", "assistant"]);
  assert.equal(transcript[1].activity.title, "T1");
  assert.equal(transcript[4].activity.title, "T2");
});

test("buildTranscript prefers live running activity when persisted blocks and runtime events both exist", () => {
  const transcript = app.buildTranscript(
    {
      messages: [
        { role: "user", content: [{ type: "text", text: "Show history" }], timestamp: 1 },
      ],
      activity_blocks: [
        {
          record_type: "activity_block",
          version: 1,
          id: "block-1",
          session_id: "session-1",
          turn_id: "1",
          created_at: 4,
          status: "done",
          title: "分析进展",
          summary: "Persisted public summary",
          event_count: 3,
          source_event_ids: ["evt-1", "evt-2", "evt-3"],
          items: [{ kind: "progress", title: "整理结论", summary: "Persisted public summary", status: "success", timestamp: 2 }],
        },
      ],
    },
    [
      { type: "turn_start", timestamp: 2, turn_id: 1 },
      { type: "reasoning_start", timestamp: 3, run_id: "run-live", turn_id: 1, message: "Preparing model context and public progress." },
      { type: "reasoning_delta", timestamp: 4, run_id: "run-live", turn_id: 1, delta: "Receiving public assistant output." },
    ],
  );

  const activityItems = transcript.filter((item) => item.role === "activity");
  assert.equal(activityItems.length, 1);
  assert.equal(activityItems[0].activity.running, true);
  assert.ok(activityItems[0].activity.summary.includes("Receiving") || activityItems[0].body.text.includes("Receiving"));
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
      { type: "message_delta", timestamp: 3, delta: "processing" },
      { type: "tool_start", timestamp: 4, tool_name: "run_shell", details: { tool_call_id: "status", command: "git status --short" } },
      { type: "tool_end", timestamp: 5, tool_name: "run_shell", message: "", details: { tool_call_id: "status", command: "git status --short", returncode: 0 } },
      { type: "turn_end", timestamp: 8 },
    ],
  );

  const activity = transcript.find((item) => item.role === "activity");
  assert.ok(activity);
  assert.equal(activity.activity.entries.some((entry) => entry.kind === "narrative"), false);
  assert.ok(activity.activity.entries.some((entry) => entry.label.length > 0));
  assert.ok(transcript.some((item) => item.role === "assistant" && item.body.text.includes("Finished the UI update.")));
  assert.ok(transcript.some((item) => item.role === "assistant" && item.body.text.length > 0));
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
  const plannerStart = activity.activity.entries.find((entry) => entry.rawType === "planner_start");
  const plannerEnd = activity.activity.entries.find((entry) => entry.rawType === "planner_end");
  assert.ok(plannerStart);
  assert.ok(plannerEnd);
  assert.ok(plannerStart.detail.length > 0);
  assert.ok(activity.body.text.includes("Edit web/src/App.tsx"));
  assert.ok(activity.body.text.includes("web/src/App.tsx"));
  assert.ok(activity.body.text.includes("npm test"));
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
  assert.ok(runningActivity.activity.title.length > 0);
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
  assert.ok(completedActivity.activity.title.length > 0);
  assert.equal(completedActivity.activity.running, false);
  assert.ok(completedActivity.activity.entries.some((entry) => entry.durationLabel === "3s"));
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
      messages: [{ role: "user", content: [{ type: "text", text: "Please run test.py and tell me the result" }], timestamp: 1 }],
    },
    [
      {
        type: "approval_result",
        timestamp: 2,
        message: "Command completed.\n\n25\n1026",
        details: { action_type: "run_shell", token: "token-1", success: true, result: "25\n1026" },
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
  assert.ok(activity.activity.title.length > 0);
  assert.equal(activity.activity.tone, "error");
  assert.ok(activity.activity.entries.some((entry) => entry.tone === "error"));
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
    console.log(`ok ${entry.name}`);
  } catch (error) {
    failures += 1;
    console.error(`fail ${entry.name}`);
    console.error(error.stack || error);
  }
}

if (failures > 0) process.exitCode = 1;
else console.log(`Passed ${tests.length} transcript tests.`);

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
