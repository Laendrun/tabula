"use strict";
// The packaged extension is one bundle (dist/extension.js, built by `npm run bundle`): it must load on its own,
// with nothing from node_modules (they aren't in the .vsix).
const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("fs");
const path = require("path");
const Module = require("module");

const bundle = path.join(__dirname, "..", "dist", "extension.js");

test("the bundle loads without node_modules", { skip: !fs.existsSync(bundle) && "run `npm run bundle` first" }, () => {
  const load = Module._load;
  const asked = [];
  Module._load = function (request, ...rest) {
    asked.push(request);
    if (request === "vscode") return new Proxy({}, { get: () => new Proxy(function () {}, { get: () => ({}) }) });
    if (!request.startsWith("node:") && !Module.builtinModules.includes(request) && request !== bundle) {
      throw new Error(`the bundle needs '${request}': it would be missing from the .vsix`);
    }
    return load.call(this, request, ...rest);
  };
  try {
    delete require.cache[bundle];
    const ext = require(bundle);
    assert.equal(typeof ext.activate, "function");
    assert.equal(typeof ext.deactivate, "function");
  } finally {
    Module._load = load;
  }
  assert.ok(asked.includes("vscode"));
});
