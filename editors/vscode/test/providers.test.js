"use strict";
// The completion and hover providers, run against a minimal stand-in for the VS Code API.
const test = require("node:test");
const assert = require("node:assert/strict");
const Module = require("module");

const registered = {};
class Range { constructor(a, b, c, d) { Object.assign(this, { start: { line: a, character: b }, end: { line: c, character: d } }); } }
class CompletionItem { constructor(label, kind) { this.label = label; this.kind = kind; } }
class MarkdownString { constructor(v) { this.value = v; } }
class Hover { constructor(contents, range) { this.contents = contents; this.range = range; } }
class Location { constructor(uri, pos) { this.uri = uri; this.range = { start: pos }; } }
class Position { constructor(line, character) { this.line = line; this.character = character; } }
const disposable = { dispose() {} };
const vscode = {
  Range, CompletionItem, MarkdownString, Hover, Location, Position,
  Uri: { file: (f) => ({ fsPath: f }) },
  CompletionItemKind: { Reference: 17, Constant: 20, Module: 8, Keyword: 13, File: 16 },
  languages: {
    createDiagnosticCollection: () => ({ set() {}, delete() {}, dispose() {} }),
    registerDocumentSymbolProvider: () => disposable,
    registerFoldingRangeProvider: () => disposable,
    registerDefinitionProvider: (sel, p) => { registered.definition = p; return disposable; },
    registerCompletionItemProvider: (sel, p, ...triggers) => { registered.completion = { p, triggers }; return disposable; },
    registerHoverProvider: (sel, p) => { registered.hover = p; return disposable; },
  },
  window: { createOutputChannel: () => ({ appendLine() {}, dispose() {} }) },
  commands: { registerCommand: () => disposable },
  workspace: {
    textDocuments: [],
    onDidOpenTextDocument: () => disposable, onDidSaveTextDocument: () => disposable,
    onDidChangeTextDocument: () => disposable, onDidCloseTextDocument: () => disposable,
    onDidChangeConfiguration: () => disposable,
  },
};
const load = Module._load;
Module._load = function (request, ...rest) { return request === "vscode" ? vscode : load.call(this, request, ...rest); };
require("../src/extension").activate({ subscriptions: [] });

function doc(text, file = "/vault/g/g.game") {
  const lines = text.split("\n");
  return { getText: () => text, lineAt: (i) => ({ text: lines[i] }), uri: { fsPath: file } };
}
const TEXT = "# Setup {#setup}\n\n- 1x [[Deck]]\n\nRead [[#\nUse the [[de\nUse the [[de]] now\n\n# Glossary\n\nDeck\n: points:: 2\n  52 cards.\n";

test("completion is triggered by [ and #", () => {
  assert.deepEqual(registered.completion.triggers, ["[", "#"]);
});

test("completes terms and adds ]] when missing", () => {
  const items = registered.completion.p.provideCompletionItems(doc(TEXT), { line: 5, character: 12 });
  assert.deepEqual(items.map((i) => i.label.label), ["Deck"]);
  assert.equal(items[0].insertText, "Deck]]");
  assert.deepEqual([items[0].range.start.character, items[0].range.end.character], [10, 12]);
  assert.equal(items[0].documentation.value, "**points:** 2\n\n52 cards.");
  const closed = registered.completion.p.provideCompletionItems(doc(TEXT), { line: 6, character: 12 });
  assert.equal(closed[0].insertText, "Deck");               // "]]" is already there
});

test("completes sections after [[#", () => {
  const items = registered.completion.p.provideCompletionItems(doc(TEXT), { line: 4, character: 8 });
  assert.deepEqual(items.map((i) => i.label.label), ["Setup", "setup", "Glossary"]);
  assert.equal(items[1].detail, "role → Setup");
});

test("no completion outside [[", () => {
  assert.equal(registered.completion.p.provideCompletionItems(doc(TEXT), { line: 0, character: 3 }), undefined);
});

test("hover on a reference", () => {
  const h = registered.hover.provideHover(doc(TEXT), { line: 2, character: 9 });
  assert.match(h.contents.value, /^\*\*Deck\*\*\n\n\*\*points:\*\* 2/);
  assert.deepEqual([h.range.start.character, h.range.end.character], [5, 13]);
  assert.equal(registered.hover.provideHover(doc(TEXT), { line: 0, character: 2 }), null);
});

// ------------------------------------------------------------------ shared fragments (on a real vault on disk)
const fs = require("fs");
const os = require("os");
const path = require("path");
const vaultDir = fs.mkdtempSync(path.join(os.tmpdir(), "tabula-vault-"));
fs.mkdirSync(path.join(vaultDir, "_shared"));
fs.mkdirSync(path.join(vaultDir, "g"));
fs.writeFileSync(path.join(vaultDir, "vault.yaml"), "name: V\n");
fs.writeFileSync(path.join(vaultDir, "_shared", "deck-52.game"), "# Components {#components}\n\n- 52x [[card]]\n\n# Glossary\n\nCard\n: One card.\n");
fs.writeFileSync(path.join(vaultDir, "_shared", "deck-52.fr.game"), "# Matériel\n\n- 52x [[carte]]\n\n# Lexique\n\nCarte\n: Une carte.\n");
fs.writeFileSync(path.join(vaultDir, "_shared", "tarot.game"), "# Tarot\n");
const GAME_FILE = path.join(vaultDir, "g", "g.game");
const FR_FILE = path.join(vaultDir, "g", "g.fr.game");

test("completes fragment names after ![[ and their sections after #", () => {
  const names = registered.completion.p.provideCompletionItems(doc("![[", GAME_FILE), { line: 0, character: 3 });
  assert.deepEqual(names.map((i) => i.label.label), ["deck-52", "tarot"]);        // translations aren't listed
  assert.equal(names[0].insertText, "deck-52]]");
  const secs = registered.completion.p.provideCompletionItems(doc("![[deck-52#]]", GAME_FILE), { line: 0, character: 11 });
  assert.deepEqual(secs.map((i) => i.label.label), ["Components", "components", "Glossary"]);
  assert.equal(secs[0].insertText, "Components");                                  // "]]" already there
  const fr = registered.completion.p.provideCompletionItems(doc("![[deck-52#", FR_FILE), { line: 0, character: 11 });
  assert.deepEqual(fr.map((i) => i.label.label), ["Matériel", "Lexique"]);         // the translated fragment
});

test("ctrl+click on an include opens the fragment at its section", () => {
  const loc = registered.definition.provideDefinition(doc("![[deck-52#glossary]]", GAME_FILE), { line: 0, character: 6 });
  assert.equal(loc.uri.fsPath, path.join(vaultDir, "_shared", "deck-52.game"));
  assert.equal(loc.range.start.line, 4);
  const fr = registered.definition.provideDefinition(doc("![[deck-52]]", FR_FILE), { line: 0, character: 6 });
  assert.equal(fr.uri.fsPath, path.join(vaultDir, "_shared", "deck-52.fr.game"));
  assert.equal(registered.definition.provideDefinition(doc("![[nope]]", GAME_FILE), { line: 0, character: 5 }), null);
});

test("hover on an include previews it", () => {
  const h = registered.hover.provideHover(doc("![[deck-52#components]]", GAME_FILE), { line: 0, character: 5 });
  assert.match(h.contents.value, /\*\*Components\*\*/);
  const missing = registered.hover.provideHover(doc("![[nope]]", GAME_FILE), { line: 0, character: 5 });
  assert.match(missing.contents.value, /No shared fragment `nope`/);
});
