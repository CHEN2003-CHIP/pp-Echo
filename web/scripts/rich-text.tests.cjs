const assert = require("assert/strict");
const fs = require("fs");
const path = require("path");
const ts = require("typescript");
const { createTempRoot } = require("./test-temp-root.cjs");

const projectRoot = path.resolve(__dirname, "..");
const tempRoot = createTempRoot("rich-text-tests");
fs.writeFileSync(path.join(tempRoot, "package.json"), JSON.stringify({ type: "commonjs" }), "utf8");
process.env.TS_ALIAS_TEMP_ROOT = tempRoot;
require("./ts-alias.cjs");

for (const sourcePath of ["src/api.ts", "src/lib/utils.ts", "src/components/ui/button.tsx", "src/components/message.tsx", "src/rich-text.tsx"]) {
  compileSource(sourcePath);
}

const rich = require(path.join(tempRoot, "src/rich-text.js"));

const tests = [];
function test(name, fn) {
  tests.push({ name, fn });
}

test("extractMessageBody collects text and image attachments", () => {
  const body = rich.extractMessageBody({
    role: "assistant",
    content: [
      { type: "text", text: "Line 1" },
      { type: "text", text: "Line 2" },
      { type: "image", url: "https://example.com/shot.png", alt: "Shot", title: "Window", mime_type: "image/png" }
    ],
    metadata: {
      attachments: [
        "https://example.com/meta-a.png",
        { url: "https://example.com/meta-b.png", alt: "Meta B", title: "Metadata title" }
      ],
      images: [
        { url: "https://example.com/meta-c.png", alt: "Meta C" }
      ]
    }
  });

  assert.equal(body.text, "Line 1\nLine 2");
  assert.equal(body.attachments.length, 4);
  assert.equal(body.attachments[0].url, "https://example.com/shot.png");
  assert.equal(body.attachments[3].alt, "Meta C");
});

test("parseMarkdown recognizes code blocks and tables", () => {
  const blocks = rich.parseMarkdown([
    "# Heading",
    "",
    "- Alpha",
    "- Beta",
    "",
    "```ts",
    "const value = 1;",
    "```",
    "",
    "| Name | Value |",
    "| --- | --- |",
    "| Alpha | 1 |"
  ].join("\n"));

  assert.equal(blocks[0].kind, "heading");
  assert.equal(blocks[1].kind, "list");
  assert.equal(blocks[2].kind, "code");
  assert.equal(blocks[2].language, "ts");
  assert.equal(blocks[2].text, "const value = 1;");
  assert.equal(blocks[3].kind, "table");
  assert.deepEqual(blocks[3].header, ["Name", "Value"]);
  assert.deepEqual(blocks[3].rows[0], ["Alpha", "1"]);
});

test("parseMarkdown treats malformed block starts as text instead of looping", () => {
  const blocks = rich.parseMarkdown([
    "```js trailing text",
    "console.log('still visible')",
    "",
    "## Markdown test",
    "",
    "```js",
    "console.log('unterminated')"
  ].join("\n"));

  assert.equal(blocks[0].kind, "paragraph");
  assert.equal(blocks[0].text, "```js trailing text console.log('still visible')");
  assert.equal(blocks[1].kind, "heading");
  assert.equal(blocks[2].kind, "code");
  assert.equal(blocks[2].language, "js");
  assert.equal(blocks[2].text, "console.log('unterminated')");
});

test("parseMarkdown handles real stored session snippets", () => {
  const markdownSession = [
    "## Markdown 测试",
    "",
    "- 列表 A",
    "- 列表 B",
    "",
    "> 这是一段引用",
    "",
    "`inline code`",
    "",
    "```js",
    "console.log(\"hello pp-Echo\")"
  ].join("\n");
  const helloSession = [
    "✅ **Orchestration completed successfully.**",
    "",
    "A patch artifact has been staged for creating `docs/worktree-smoke-web.md` with the content:",
    "```",
    "pp-Echo isolated worktree smoke test",
    "```"
  ].join("\n");

  assert.ok(rich.parseMarkdown(markdownSession).length > 0);
  assert.ok(rich.parseMarkdown(helloSession).length > 0);
});

test("parseMarkdown falls back for excessive line counts", () => {
  const blocks = rich.parseMarkdown(Array.from({ length: 1300 }, (_, index) => `line ${index}`).join("\n"));
  assert.equal(blocks.length, 1);
  assert.equal(blocks[0].kind, "code");
});

test("sanitizeMediaUrl only permits safe media URLs", () => {
  assert.equal(rich.sanitizeMediaUrl("https://example.com/image.png", { allowRelative: true }), "https://example.com/image.png");
  assert.equal(rich.sanitizeMediaUrl("data:image/png;base64,abc", { allowRelative: true }), "data:image/png;base64,abc");
  assert.equal(rich.sanitizeMediaUrl("blob:https://example.com/id", { allowRelative: true }), "blob:https://example.com/id");
  assert.equal(rich.sanitizeMediaUrl(`data:image/png;base64,${"a".repeat(5000)}`, { allowRelative: true }), null);
  assert.equal(rich.sanitizeMediaUrl("javascript:alert(1)", { allowRelative: true }), null);
  assert.equal(rich.sanitizeMediaUrl("file:///tmp/image.png", { allowRelative: true }), null);
});

test("partitionVisibleAttachments keeps a small default attachment budget", () => {
  const attachments = Array.from({ length: 5 }, (_, index) => ({ url: `https://example.com/${index}.png` }));
  const result = rich.partitionVisibleAttachments(attachments);
  assert.equal(result.visible.length, 3);
  assert.equal(result.hiddenCount, 2);
  assert.equal(rich.MAX_VISIBLE_ATTACHMENTS, 3);
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
  console.log(`Passed ${tests.length} rich-text tests.`);
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
      isolatedModules: true
    },
    fileName: absoluteSourcePath
  });
  fs.writeFileSync(outputPath, result.outputText, "utf8");
}
