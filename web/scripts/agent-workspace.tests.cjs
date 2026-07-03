const assert = require("assert/strict");
const fs = require("fs");
const path = require("path");
const ts = require("typescript");
const { createTempRoot } = require("./test-temp-root.cjs");

const projectRoot = path.resolve(__dirname, "..");
const tempRoot = createTempRoot("agent-workspace-tests");
fs.writeFileSync(path.join(tempRoot, "package.json"), JSON.stringify({ type: "commonjs" }), "utf8");
process.env.TS_ALIAS_TEMP_ROOT = tempRoot;
require("./ts-alias.cjs");

compileSource("src/lib/mockCodingTask.ts");
compileSource("src/lib/codingTaskApi.ts");
const mock = require(path.join(tempRoot, "src/lib/mockCodingTask.js"));
const api = require(path.join(tempRoot, "src/lib/codingTaskApi.js"));
const appSource = fs.readFileSync(path.join(projectRoot, "src/App.tsx"), "utf8");

assert.ok(!appSource.includes("shouldUseCodingWorkflowMock"));
assert.ok(!appSource.includes("AgentWorkspaceResult"));
assert.ok(!appSource.includes("buildWorkspaceTranscript"));
assert.ok(!appSource.includes("createCodingTaskClient"));
assert.ok(appSource.includes("sendPrompt();"));

const state = mock.mockCodingTaskState("implement unified workspace");

assert.equal(typeof state.task_id, "string");
assert.equal(state.task, "implement unified workspace");
assert.equal(state.status, "awaiting_approval");
assert.ok(Array.isArray(state.timeline_blocks));
assert.ok(state.timeline_blocks.some((block) => block.type === "plan"));
assert.ok(state.timeline_blocks.some((block) => block.type === "task_scope"));
assert.ok(state.timeline_blocks.some((block) => block.type === "change_impact"));
assert.ok(state.timeline_blocks.some((block) => block.type === "validation_plan"));
assert.ok(state.pending_approvals.length > 0);
assert.equal(state.pending_approvals[0].token, "mock-token-run-tests");
assert.equal(state.pending_approvals[0].payload, undefined);
assert.ok(state.validation_commands.some((command) => command.command === "npm run build"));
assert.deepEqual(Object.keys(mock.emptyCodingTaskState.runtime_counters).sort(), ["patch_candidates", "shell_commands", "tool_calls"]);

runAdapterTests()
  .then(() => {
    console.log("Passed agent workspace adapter tests.");
  })
  .finally(() => {
    fs.rmSync(tempRoot, { recursive: true, force: true });
  });

async function runAdapterTests() {
  const mockClient = new api.MockCodingTaskClient();
  const mockState = await mockClient.startTask("fix repo tests");
  assert.equal(mockState.task, "fix repo tests");
  assert.equal(mockState.pending_approvals[0].payload, undefined);
  const approvedMock = await mockClient.approveAction(mockState.task_id, mockState.pending_approvals[0].token);
  assert.equal(approvedMock.pending_approvals.length, 0);
  assert.ok(approvedMock.timeline_blocks.some((block) => block.type === "approval_result"));
  const rejectMockStart = await mockClient.startTask("reject repo tests");
  const rejectedMock = await mockClient.rejectAction(rejectMockStart.task_id, rejectMockStart.pending_approvals[0].token, "No");
  assert.equal(rejectedMock.pending_approvals.length, 0);
  assert.ok(rejectedMock.warnings.some((warning) => warning.includes("Mock rejection")));

  const defaultClient = api.createCodingTaskClient({});
  assert.equal(defaultClient.constructor.name, "MockCodingTaskClient");
  const realClient = api.createCodingTaskClient({ VITE_CODING_TASK_API: "real", VITE_API_BASE_URL: "https://example.test" });
  assert.equal(realClient.constructor.name, "HttpCodingTaskClient");

  const requests = [];
  const httpState = mock.mockCodingTaskState("inspect api");
  const httpClient = new api.HttpCodingTaskClient("https://api.test/", async (url, init) => {
    requests.push({ url, init });
    return fakeResponse(200, "OK", httpState);
  });
  const result = await httpClient.startTask("inspect api", { workspace: "E:/repo", max_turns: 2, prepare_only: true });
  assert.equal(result.task, "inspect api");
  assert.equal(requests[0].url, "https://api.test/api/coding/tasks");
  assert.equal(requests[0].init.method, "POST");
  assert.equal(requests[0].init.headers["Content-Type"], "application/json");
  assert.deepEqual(JSON.parse(requests[0].init.body), {
    task: "inspect api",
    workspace: "E:/repo",
    max_turns: 2,
    prepare_only: true
  });
  await httpClient.approveAction("task/one", "tok/one");
  await httpClient.rejectAction("task/one", "tok/two", "No");
  assert.equal(requests[1].url, "https://api.test/api/coding/tasks/task%2Fone/approvals/tok%2Fone/approve");
  assert.deepEqual(JSON.parse(requests[1].init.body), { confirm: true });
  assert.equal(requests[2].url, "https://api.test/api/coding/tasks/task%2Fone/approvals/tok%2Ftwo/reject");
  assert.deepEqual(JSON.parse(requests[2].init.body), { reason: "No" });

  const errorClient = new api.HttpCodingTaskClient("", async () => fakeResponse(500, "Server Error", { error: "controlled loop unavailable" }));
  await assert.rejects(
    () => errorClient.startTask("fix build"),
    /Coding task API request failed \(500 Server Error\): controlled loop unavailable/
  );

  const invalidClient = new api.HttpCodingTaskClient("", async () => fakeResponse(200, "OK", { task_id: "x" }));
  await assert.rejects(
    () => invalidClient.startTask("fix build"),
    /incomplete CodingTaskState: missing task, status, timeline_blocks/
  );
}

function fakeResponse(status, statusText, payload) {
  return {
    ok: status >= 200 && status < 300,
    status,
    statusText,
    headers: {
      get(name) {
        return name.toLowerCase() === "content-type" ? "application/json" : "";
      }
    },
    async json() {
      return payload;
    },
    async text() {
      return JSON.stringify(payload);
    }
  };
}

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
      isolatedModules: true
    },
    fileName: absoluteSourcePath
  });
  fs.writeFileSync(outputPath, result.outputText, "utf8");
}
