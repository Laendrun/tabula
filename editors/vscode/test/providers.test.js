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
const disposable = { dispose() {} };
const vscode = {
  Range, CompletionItem, MarkdownString, Hover,
  CompletionItemKind: { Reference: 17, Constant: 20, Module: 8, Keyword: 13 },
  languages: {
    createDiagnosticCollection: () => ({ set() {}, delete() {}, dispose() {} }),
    registerDocumentSymbolProvider: () => disposable,
    registerFoldingRangeProvider: () => disposable,
    registerDefinitionProvider: () => disposable,
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
