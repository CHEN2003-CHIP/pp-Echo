const fs = require("fs");
const Module = require("module");
const os = require("os");
const path = require("path");

const projectRoot = path.resolve(__dirname, "..");
const projectNodeModules = path.join(projectRoot, "node_modules");

function createTempRoot(name) {
  if (fs.existsSync(projectNodeModules)) {
    const entries = process.env.NODE_PATH ? process.env.NODE_PATH.split(path.delimiter) : [];
    if (!entries.includes(projectNodeModules)) {
      process.env.NODE_PATH = [projectNodeModules, ...entries].filter(Boolean).join(path.delimiter);
      Module._initPaths();
    }
  }
  return fs.mkdtempSync(path.join(os.tmpdir(), `pp-echo-${name}-`));
}

module.exports = { createTempRoot };
