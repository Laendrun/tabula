"use strict";
const test = require("node:test");
const assert = require("node:assert/strict");
const core = require("../src/core");

test("check arguments", () => {
  assert.deepEqual(core.checkArgs({ file: "a.game", stdin: true }), ["check", "a.game", "--json", "--stdin"]);
  assert.deepEqual(core.checkArgs({ file: "a.game", spell: true }), ["check", "a.game", "--json", "--spell"]);
  assert.deepEqual(core.fmtArgs({ file: "a.game", vault: "V" }), ["--vault", "V", "fmt", "a.game", "--stdin"]);
  assert.deepEqual(core.fmtArgs({ extraArgs: ["t.py"] }), ["t.py", "fmt"]);
  assert.deepEqual(core.previewArgs({ file: "a.sheet" }), ["sheet", "a.sheet", "--stdin", "-o", "-"]);
  assert.deepEqual(core.previewArgs({ file: "a.game", vault: "V" }), ["--vault", "V", "export", "a.game", "--interactive", "--lines", "--stdin", "-o", "-"]);
  assert.deepEqual(
    core.checkArgs({ vault: "V", extraArgs: ["cli/tabula.py"], definitions: true }),
    ["cli/tabula.py", "--vault", "V", "check", "--json", "--definitions"]
  );
});

test("settings expansion", () => {
  assert.equal(core.expand("${workspaceFolder}/cli/tabula.py", "/w", "/h"), "/w/cli/tabula.py");
  assert.equal(core.expand("~/vault", "/w", "/h"), "/h/vault");
  assert.equal(core.expand("tabula", "/w", "/h"), "tabula");
});

test("parse check output", () => {
  const r = core.parseCheckOutput('{"vault": "/v", "files": ["/v/g/g.game"], "issues": []}');
  assert.deepEqual(r, { vault: "/v", files: ["/v/g/g.game"], issues: [] });
  assert.throws(() => core.parseCheckOutput("usage: tabula ..."), /no JSON/);
});

test("squiggle goes on what the message quotes", () => {
  const msg = "[[nope]] matches no component ('- 1x [[nope]]' in a list) and no definition ('nope' then ': …')";
  assert.deepEqual(core.issueColumns("See the [[nope]] card.", msg), [8, 16]);
  assert.deepEqual(core.issueColumns("## Setup {2x}", "invalid heading attributes '{2x}' (roles look like #glossary)"), [9, 13]);
  assert.deepEqual(core.issueColumns("  some text  ", "something without quotes"), [2, 11]);
  assert.deepEqual(core.issueColumns("", "empty line"), [0, 0]);
  // a word: the whole word, not the same letters inside a longer one
  assert.deepEqual(core.issueColumns("Les cartes, la carte.", "unknown word 'carte'"), [15, 20]);
  assert.deepEqual(core.issueColumns("coup d'oeil", "unknown word 'd'oeil'"), [5, 11]);
});

test("fold is case, accent and plural insensitive", () => {
  assert.equal(core.fold("Événements"), core.fold("evenement"));
  assert.equal(core.fold("Cartes Puissance"), core.fold("carte puissance"));
  assert.notEqual(core.fold("Pass"), core.fold("Pa"));
});

test("TODO reminders are information, not warnings", () => {
  const S = { Error: 0, Warning: 1, Information: 2 };
  assert.equal(core.severity("error", S), 0);
  assert.equal(core.severity("warning", S), 1);
  assert.equal(core.severity("todo", S), 2);
  assert.equal(core.severity("spelling", S), 2);
});

test("the schemas come from the spec when building", () => {
  const fs = require("fs");
  const os = require("os");
  const path = require("path");
  const { copySchemas, SPEC } = require("../scripts/copy-schemas");
  const to = fs.mkdtempSync(path.join(os.tmpdir(), "tabula-schemas-"));
  const names = copySchemas(to);
  for (const name of ["game", "sheet", "vault", "wishlist"]) {
    const file = `${name}.schema.json`;
    assert.ok(names.includes(file), file);
    assert.equal(fs.readFileSync(path.join(to, file), "utf8"), fs.readFileSync(path.join(SPEC, file), "utf8"));
  }
  // what package.json points to is one of them
  const pkg = JSON.parse(fs.readFileSync(path.join(__dirname, "..", "package.json"), "utf8"));
  for (const v of pkg.contributes.jsonValidation || []) {
    assert.match(v.url, /^\.\/schemas\/[\w.-]+\.schema\.json$/);
    assert.ok(names.includes(path.basename(v.url)), v.url);
  }
});

