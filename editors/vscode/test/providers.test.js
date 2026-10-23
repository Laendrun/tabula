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
class Location { constructor(uri, pos) { this.uri = uri; this.range = pos && pos.start ? pos : { start: pos }; } }
class Position { constructor(line, character) { this.line = line; this.character = character; } }
class WorkspaceEdit {
  constructor() { this.ops = []; }
  createFile(uri, opts) { this.ops.push({ create: uri, contents: opts.contents }); }
  replace(uri, range, text) { this.ops.push({ uri, range, text }); }
  insert(uri, pos, text) { this.ops.push({ uri, range: { start: pos, end: pos }, text }); }
}
class CodeLens { constructor(range, command) { this.range = range; this.command = command; } }
class DocumentLink { constructor(range, target) { this.range = range; this.target = target; } }
class InlayHint { constructor(position, label) { this.position = position; this.label = label; } }
class DocumentDropEdit { constructor(insertText) { this.insertText = insertText; } }
class DocumentPasteEdit { constructor(insertText, title, kind) { this.insertText = insertText; this.title = title; this.kind = kind; } }
class TreeItem { constructor(label, state) { this.label = label; this.collapsibleState = state; } }
class ThemeIcon { constructor(id, color) { this.id = id; this.color = color; } }
class ThemeColor { constructor(id) { this.id = id; } }
class EventEmitter { constructor() { this.listeners = []; this.event = (f) => { this.listeners.push(f); return disposable; }; } fire(x) { this.listeners.forEach((f) => f(x)); } }
class Selection { constructor(a, b) { this.anchor = a; this.active = b; } }
class TextEdit { static replace(range, text) { return { range, text }; } }
class CodeAction { constructor(title, kind) { this.title = title; this.kind = kind; } }
const disposable = { dispose() {} };
const vscode = {
  Range, CompletionItem, MarkdownString, Hover, Location, Position, WorkspaceEdit, CodeAction, TextEdit, Selection, CodeLens, DocumentLink, InlayHint, DocumentDropEdit, DocumentPasteEdit, TreeItem, ThemeIcon, ThemeColor, EventEmitter,
  TreeItemCollapsibleState: { None: 0, Collapsed: 1, Expanded: 2 }, DiagnosticSeverity: { Error: 0, Warning: 1, Information: 2, Hint: 3 },
  ProgressLocation: { Window: 10, Notification: 15 },
  TextEditorRevealType: { InCenterIfOutsideViewport: 2 },
  CodeActionKind: { QuickFix: "quickfix" },
  Uri: { file: (f) => ({ fsPath: f, scheme: "file", toString: () => "file://" + f }), parse: (u) => u.startsWith("file://") ? ({ fsPath: u.slice(7), scheme: "file", toString: () => u }) : ({ toString: () => u }) },
  CompletionItemKind: { Reference: 17, Constant: 20, Module: 8, Keyword: 13, File: 16 },
  languages: {
    createDiagnosticCollection: () => ({ set() {}, delete() {}, dispose() {} }),
    registerDocumentSymbolProvider: () => disposable,
    registerFoldingRangeProvider: () => disposable,
    registerDefinitionProvider: (sel, p) => { registered.definition = p; return disposable; },
    registerCompletionItemProvider: (sel, p, ...triggers) => { registered.completion = { p, triggers }; return disposable; },
    registerHoverProvider: (sel, p) => { registered.hover = p; return disposable; },
    registerCodeActionsProvider: (sel, p) => { registered.actions = p; return disposable; },
    registerRenameProvider: (sel, p) => { registered.rename = p; return disposable; },
    registerDocumentFormattingEditProvider: (sel, p) => { registered.formatter = p; return disposable; },
    registerReferenceProvider: (sel, p) => { registered.references = p; return disposable; },
    registerCodeLensProvider: (sel, p) => { registered.lenses = p; return disposable; },
    registerDocumentLinkProvider: (sel, p) => { registered.links = p; return disposable; },
    registerInlayHintsProvider: (sel, p) => { registered.hints = p; return disposable; },
    getDiagnostics: (uri) => (registered.diags || {})[uri.fsPath] || [],
    onDidChangeDiagnostics: () => disposable,
    registerDocumentDropEditProvider: (sel, p) => { registered.drop = p; return disposable; },
    registerDocumentPasteEditProvider: (sel, p, meta) => { registered.paste = p; registered.pasteMeta = meta; return disposable; },
  },
  window: {
    createOutputChannel: () => ({ appendLine() {}, dispose() {} }),
    onDidChangeActiveTextEditor: () => disposable,
    registerTreeDataProvider: (id, p) => { (registered.trees = registered.trees || {})[id] = p; return disposable; },
    withProgress: (o, f) => f(),
    onDidChangeTextEditorSelection: (f) => { registered.onSelection = f; return disposable; },
    showTextDocument: (doc) => { const ed = { document: doc, revealRange(r) { ed.revealed = r; } }; registered.shown = ed; return Promise.resolve(ed); },
    activeTextEditor: null,
    setStatusBarMessage() {},
    showInformationMessage() {},
    createWebviewPanel: (id, title) => {
      const panel = {
        title, html: "", messages: [],
        webview: { cspSource: "vscode-test:", postMessage: (m) => { (panel.posted = panel.posted || []).push(m); return Promise.resolve(true); }, set html(v) { panel.html = v; panel.onHtml && panel.onHtml(v); },
                   get html() { return panel.html; }, onDidReceiveMessage: (f) => { panel.receive = f; return disposable; } },
        reveal() {}, onDidDispose: () => disposable,
      };
      registered.panel = panel;
      return panel;
    },
  },
  ViewColumn: { One: 1, Beside: -2 },
  env: { openExternal: (u) => { registered.opened = u; } },
  commands: { registerCommand: (name, f) => { (registered.commands = registered.commands || {})[name] = f; return disposable; } },
  workspace: {
    getConfiguration: () => ({ get: (k) => registered.config && registered.config[k] }),
    getWorkspaceFolder: () => null,
    workspaceFolders: [],
    textDocuments: [],
    onDidOpenTextDocument: () => disposable, onDidSaveTextDocument: () => disposable,
    onDidChangeTextDocument: () => disposable, onDidCloseTextDocument: () => disposable,
    onDidChangeConfiguration: () => disposable,
  },
};
const load = Module._load;
Module._load = function (request, ...rest) { return request === "vscode" ? vscode : load.call(this, request, ...rest); };
// the real tabula (from this repository) answers the extension's `tabula outline` calls
const fs = require("fs");
const os = require("os");
const path = require("path");
process.env.PYTHONPATH = path.join(__dirname, "..", "..", "..", "cli") + (process.env.PYTHONPATH ? path.delimiter + process.env.PYTHONPATH : "");
const PYTHON = process.env.PYTHON || (process.platform === "win32" ? "python" : "python3");
const realTabula = () => { registered.config = { path: PYTHON, extraArgs: ["-m", "tabula"] }; };
realTabula();
const baseVault = fs.mkdtempSync(path.join(os.tmpdir(), "tabula-base-"));
fs.writeFileSync(path.join(baseVault, "vault.yaml"), "name: Base\n");
fs.mkdirSync(path.join(baseVault, "g"));
const DEFAULT_FILE = path.join(baseVault, "g", "g.game");

require("../src/extension").activate({ subscriptions: [] });

function doc(text, file = DEFAULT_FILE) {
  const lines = text.split("\n");
  return { getText: () => text, lineAt: (i) => ({ text: lines[i] }), languageId: "tabula", lineCount: lines.length,
           uri: { fsPath: file, scheme: "file", toString: () => "file://" + file } };
}
const TEXT = "# Setup {#setup}\n\n- 1x [[Deck]]\n\nRead [[#\nUse the [[de\nUse the [[de]] now\n\n# Glossary\n\nDeck\n: points:: 2\n  52 cards.\n";

test("completion is triggered by [ and #", async () => {
  realTabula();
  assert.deepEqual(registered.completion.triggers, ["[", "#", "="]);
});

test("completes terms and adds ]] when missing", async () => {
  realTabula();
  const items = await registered.completion.p.provideCompletionItems(doc(TEXT), { line: 5, character: 12 });
  assert.deepEqual(items.map((i) => i.label.label), ["Deck"]);
  assert.equal(items[0].insertText, "Deck]]");
  assert.deepEqual([items[0].range.start.character, items[0].range.end.character], [10, 12]);
  assert.equal(items[0].documentation.value, "**points:** 2\n\n52 cards.");
  const closed = await registered.completion.p.provideCompletionItems(doc(TEXT), { line: 6, character: 12 });
  assert.equal(closed[0].insertText, "Deck");               // "]]" is already there
});

test("completes sections after [[#", async () => {
  realTabula();
  const items = await registered.completion.p.provideCompletionItems(doc(TEXT), { line: 4, character: 8 });
  assert.deepEqual(items.map((i) => i.label.label), ["Setup", "setup", "Glossary"]);
  assert.equal(items[1].detail, "role → Setup");
});

test("no completion outside [[", async () => {
  realTabula();
  assert.equal(await registered.completion.p.provideCompletionItems(doc(TEXT), { line: 0, character: 3 }), undefined);
});

test("hover on a reference", async () => {
  realTabula();
  const h = await registered.hover.provideHover(doc(TEXT), { line: 2, character: 9 });
  assert.match(h.contents.value, /^\*\*Deck\*\*\n\n\*\*points:\*\* 2/);
  assert.deepEqual([h.range.start.character, h.range.end.character], [5, 13]);
  assert.equal(await registered.hover.provideHover(doc(TEXT), { line: 0, character: 2 }), null);
});

// ------------------------------------------------------------------ shared fragments (on a real vault on disk)
const vaultDir = fs.mkdtempSync(path.join(os.tmpdir(), "tabula-vault-"));
fs.mkdirSync(path.join(vaultDir, "_shared"));
fs.mkdirSync(path.join(vaultDir, "g"));
fs.writeFileSync(path.join(vaultDir, "vault.yaml"), "name: V\n");
fs.writeFileSync(path.join(vaultDir, "_shared", "deck-52.game"), "# Components {#components}\n\n- 52x [[card]]\n\n# Glossary\n\nCard\n: One card.\n");
fs.writeFileSync(path.join(vaultDir, "_shared", "deck-52.fr.game"), "# Matériel\n\n- 52x [[carte]]\n\n# Lexique\n\nCarte\n: Une carte.\n");
fs.writeFileSync(path.join(vaultDir, "_shared", "tarot.game"), "# Tarot\n");
const GAME_FILE = path.join(vaultDir, "g", "g.game");
const FR_FILE = path.join(vaultDir, "g", "g.fr.game");

test("completes fragment names after ![[ and their sections after #", async () => {
  realTabula();
  const names = await registered.completion.p.provideCompletionItems(doc("![[", GAME_FILE), { line: 0, character: 3 });
  assert.deepEqual(names.map((i) => i.label.label), ["deck-52", "tarot"]);        // translations aren't listed
  assert.equal(names[0].insertText, "deck-52]]");
  const secs = await registered.completion.p.provideCompletionItems(doc("![[deck-52#]]", GAME_FILE), { line: 0, character: 11 });
  assert.deepEqual(secs.map((i) => i.label.label), ["Components", "components", "Glossary"]);
  assert.equal(secs[0].insertText, "Components");                                  // "]]" already there
  const fr = await registered.completion.p.provideCompletionItems(doc("![[deck-52#", FR_FILE), { line: 0, character: 11 });
  assert.deepEqual(fr.map((i) => i.label.label), ["Matériel", "Lexique"]);         // the translated fragment
});

test("ctrl+click on an include opens the fragment at its section", async () => {
  realTabula();
  const loc = await registered.definition.provideDefinition(doc("![[deck-52#glossary]]", GAME_FILE), { line: 0, character: 6 });
  assert.equal(loc.uri.fsPath, path.join(vaultDir, "_shared", "deck-52.game"));
  assert.equal(loc.range.start.line, 4);
  const fr = await registered.definition.provideDefinition(doc("![[deck-52]]", FR_FILE), { line: 0, character: 6 });
  assert.equal(fr.uri.fsPath, path.join(vaultDir, "_shared", "deck-52.fr.game"));
  assert.equal(await registered.definition.provideDefinition(doc("![[nope]]", GAME_FILE), { line: 0, character: 5 }), null);
});

test("hover on an include previews it", async () => {
  realTabula();
  const h = await registered.hover.provideHover(doc("![[deck-52#components]]", GAME_FILE), { line: 0, character: 5 });
  assert.match(h.contents.value, /^\*from `_shared\/deck-52` — components\*\n\n- 52x card/);
  const missing = await registered.hover.provideHover(doc("![[nope]]", GAME_FILE), { line: 0, character: 5 });
  assert.match(missing.contents.value, /No shared fragment `nope`/);
});

test("terms from included fragments: completion, hover, ctrl+click", async () => {
  realTabula();
  const text = "# Kit\n\n![[deck-52#components]]\n\n# Words\n\n![[deck-52#glossary]]\n\nUse a [[ca\nA [[card]] here.\n";
  const items = await registered.completion.p.provideCompletionItems(doc(text, GAME_FILE), { line: 8, character: 10 });
  assert.deepEqual(items.map((i) => i.label.label), ["Card"]);
  const h = await registered.hover.provideHover(doc(text, GAME_FILE), { line: 9, character: 5 });
  assert.match(h.contents.value, /^\*\*Card\*\*\n\nOne card\./);
  const loc = await registered.definition.provideDefinition(doc(text, GAME_FILE), { line: 9, character: 5 });
  assert.equal(loc[0].uri.fsPath, path.join(vaultDir, "_shared", "deck-52.game"));
  assert.equal(loc[0].range.start.line, 6);
});

test("preview: renders the open file with tabula and handles links", async () => {
  realTabula();
  // a fake tabula that answers like `tabula export FILE --interactive --stdin -o -`
  const fake = path.join(vaultDir, "fake-tabula.js");
  fs.writeFileSync(fake, `let s='';process.stdin.on('data',d=>s+=d).on('end',()=>{
    const args=process.argv.slice(2);
    if(!args.includes('--interactive')||!args.includes('--stdin')){process.stderr.write('bad args '+args.join(' '));process.exit(2);}
    process.stdout.write('<!doctype html><html><head><title>t</title></head><body><p>'+s.length+' chars</p><script>run()</script></body></html>');});`);
  registered.config = { path: process.execPath, extraArgs: [fake] };
  const d = doc("# Rules\n\nHello.\n", GAME_FILE);
  vscode.window.activeTextEditor = { document: d };
  const shown = new Promise((resolve) => { registered.onPanel = resolve; });
  registered.commands["tabula.openPreview"]();
  const panel = registered.panel;
  const html = await new Promise((resolve) => { panel.onHtml = resolve; });
  assert.match(html, /<p>16 chars<\/p>/);                                     // the unsaved text went to tabula
  assert.match(html, /Content-Security-Policy/);
  assert.match(html, /<script nonce="[a-z0-9]+">run\(\)/);                     // the page's own script may run
  assert.equal(panel.title, "Preview: g.game");
  panel.receive({ open: "https://example.com/x" });
  assert.equal(String(registered.opened), "https://example.com/x");
  // the preview follows the cursor, and a double-click in it moves the cursor
  registered.onSelection({ textEditor: { document: d }, selections: [{ active: { line: 2 } }] });
  await new Promise((r) => setTimeout(r, 200));
  assert.deepEqual(panel.posted.pop(), { line: 3 });
  panel.receive({ line: 3 });
  await new Promise((r) => setTimeout(r, 10));
  assert.equal(registered.shown.selection.active.line, 2);
  assert.match(html, /addEventListener\('dblclick'/);
  void shown;
});


test("quick fixes and rename, through the VS Code API", async () => {
  realTabula();
  const fs = require("fs"), os = require("os"), path = require("path");
  const root = fs.mkdtempSync(path.join(os.tmpdir(), "tabula-fix-"));
  fs.writeFileSync(path.join(root, "vault.yaml"), "language: en\n");
  fs.mkdirSync(path.join(root, "g"));
  const file = path.join(root, "g", "g.game");
  const text = "# Play\n\nDraw a [[Dek]], or a crad.\n\n# Glossary {#glossary}\n\nDeck\n: 52 cards.\n";
  fs.writeFileSync(file, text);
  const d = doc(text, file);
  const diag = (line, a, b, message) => ({ source: "tabula", message, range: new Range(line, a, line, b) });
  const actions = await registered.actions.provideCodeActions(d, null, { diagnostics: [
    diag(2, 7, 14, "[[Dek]] matches no component ('- 1x [[Dek]]' in a list) and no definition ('Dek' then ': …')"),
    diag(2, 21, 25, "unknown word 'crad'"),
    { source: "other", message: "x", range: new Range(0, 0, 0, 1) },
  ] });
  assert.deepEqual(actions.map((a) => a.title), ["Change to [[Deck]]", "Define 'Dek' in the glossary", "Add 'crad' to words.txt"]);
  assert.equal(actions[0].isPreferred, true);
  assert.equal(actions[0].edit.ops[0].text, "[[Deck]]");
  assert.equal(actions[1].edit.ops[0].range.start.line, 8);          // past the end: appended
  assert.equal(actions[1].edit.ops[0].text, "\nDek\n: \n\n");
  registered.commands["tabula.addWord"](...actions[2].command.arguments);
  registered.commands["tabula.addWord"](...actions[2].command.arguments);   // only once
  assert.equal(fs.readFileSync(path.join(root, "words.txt"), "utf8").split("\n").filter((l) => l === "crad").length, 1);

  const prep = await registered.rename.prepareRename(d, { line: 6, character: 1 });
  assert.equal(prep.placeholder, "Deck");
  const we = await registered.rename.provideRenameEdits(d, { line: 6, character: 1 }, "Pack");
  assert.deepEqual(we.ops.map((o) => o.text), ["Pack"]);             // [[Dek]] isn't a reference to Deck
  await assert.rejects(() => registered.rename.prepareRename(d, { line: 1, character: 0 }), /Put the cursor/);
});

test("formatting runs tabula fmt FILE --stdin and replaces the text", async () => {
  realTabula();
  // a fake tabula that answers like `tabula fmt FILE --stdin`: trailing spaces removed, "BAD" refused
  const fake = path.join(vaultDir, "fake-fmt.js");
  fs.writeFileSync(fake, `let s='';process.stdin.on('data',d=>s+=d).on('end',()=>{
    const a=process.argv.slice(2), i=a.indexOf('fmt');
    if(i<0||a[i+2]!=='--stdin'){process.stderr.write('bad args '+a.join(' '));process.exit(2);}
    if(s.includes('BAD')){process.stdout.write(s);process.stderr.write('tabula: not formatted: the result would read differently');process.exit(1);}
    process.stdout.write(s.replace(/ +$/gm,''));});`);
  registered.config = { path: process.execPath, extraArgs: [fake] };
  const edits = await registered.formatter.provideDocumentFormattingEdits(doc("# Rules  \n\nText.   \n", GAME_FILE));
  assert.equal(edits.length, 1);
  assert.equal(edits[0].text, "# Rules\n\nText.\n");
  assert.deepEqual([edits[0].range.start.line, edits[0].range.end.line, edits[0].range.end.character], [0, 3, 0]);
  assert.deepEqual(await registered.formatter.provideDocumentFormattingEdits(doc("# Tidy\n", GAME_FILE)), []);
  assert.deepEqual(await registered.formatter.provideDocumentFormattingEdits(doc("BAD  \n", GAME_FILE)), []);
  assert.ok(registered.commands["tabula.formatFile"] && registered.commands["tabula.formatVault"]);
});

test("values: completion after {= and hover, from the game and vault.yaml", async () => {
  realTabula();
  const root = fs.mkdtempSync(path.join(require("os").tmpdir(), "tabula-val-"));
  fs.writeFileSync(path.join(root, "vault.yaml"), 'values:\n  target: 100\n  hand: {2p: 9, "*": 5}\n');
  fs.mkdirSync(path.join(root, "g"));
  const file = path.join(root, "g", "g.game");
  const text = '---\ntitle: G\nvalues:\n  hand: {2p: 7, "*": 5}\n---\n# Rules\n\nDeal {=\nPlay to {=target} points.\n';
  const d = doc(text, file);
  const items = await registered.completion.p.provideCompletionItems(d, { line: 7, character: 7 });
  assert.deepEqual(items.map((i) => [i.label.label, i.insertText, i.detail]),
    [["hand", "hand}", "value from this file"], ["target", "target}", "value from vault.yaml"]]);
  assert.equal(items[0].label.description, "2p 7 · * 5");
  const h = await registered.hover.provideHover(d, { line: 8, character: 12 });
  assert.equal(h.contents.value, "**target** = `100`\n\nfrom vault.yaml");
});

test("symbols: completion after :x and hover, from the game and vault.yaml", async () => {
  realTabula();
  const root = fs.mkdtempSync(path.join(require("os").tmpdir(), "tabula-sym-"));
  fs.writeFileSync(path.join(root, "vault.yaml"), "symbols:\n  gold: media/gold.png\n");
  fs.mkdirSync(path.join(root, "g"));
  const file = path.join(root, "g", "g.game");
  const text = '---\ntitle: G\nsymbols:\n  star: "⭐"\n---\n# Rules\n\nPay 3 :g\nScore :star: now.\n';
  const d = doc(text, file);
  const items = await registered.completion.p.provideCompletionItems(d, { line: 7, character: 8 });
  assert.deepEqual(items.map((i) => [i.label.label, i.insertText, i.range.start.character]), [[":star:", ":star:", 6], [":gold:", ":gold:", 6]]);
  const h = await registered.hover.provideHover(d, { line: 8, character: 8 });
  assert.equal(h.contents.value, "⭐  `:star:`\n\nfrom this file");
  const g = await registered.hover.provideHover(doc("Pay :gold:\n", file), { line: 0, character: 6 });
  assert.match(g.contents.value, /^!\[gold\]\(file:.*media\/gold\.png\|height=32\)/);
});

test("references, use counts, links, image hover and inline values", async () => {
  realTabula();
  const root = fs.mkdtempSync(path.join(require("os").tmpdir(), "tabula-nav-"));
  fs.mkdirSync(path.join(root, "_shared"));
  fs.writeFileSync(path.join(root, "_shared", "deck.game"), "# Deck\n");
  fs.mkdirSync(path.join(root, "g", "media"), { recursive: true });
  fs.writeFileSync(path.join(root, "g", "media", "gift.png"), "x");
  const file = path.join(root, "g", "g.game");
  const text = "---\ntitle: G\nvalues:\n  hand: {2p: 7, \"*\": 5}\n---\n# Play\n\nDeal {=hand}. Play a [[Gift]], then [[gifts]].\n" +
    "See [[#Cards]].\n\n![[deck]]\n\n# Cards\n\nGift\n: image:: media/gift.png\n  Give.\n\nLost\n: image:: media/none.png\n  X.\n";
  const d = doc(text, file);
  const refs = await registered.references.provideReferences(d, { line: 7, character: 25 }, { includeDeclaration: true });
  assert.deepEqual(refs.map((r) => r.range.start.line), [14, 7, 7]);            // the definition, then 2 references
  const lenses = await registered.lenses.provideCodeLenses(d);
  assert.deepEqual(lenses.map((l) => [l.range.start.line, l.command.title]), [[12, "used once"], [14, "used 2 times"], [18, "not used"]]);
  assert.equal(lenses[1].command.command, "editor.action.showReferences");
  assert.equal(lenses[1].command.arguments[2].length, 2);
  const links = await registered.links.provideDocumentLinks(d);
  assert.deepEqual(links.map((l) => [l.range.start.line, path.basename(l.target.fsPath)]), [[10, "deck.game"], [15, "gift.png"]]);
  const h = await registered.hover.provideHover(d, { line: 15, character: 15 });
  assert.match(h.contents.value, /^!\[\]\(file:.*gift\.png\|height=220\)/);
  assert.match((await registered.hover.provideHover(d, { line: 19, character: 15 })).contents.value, /Image not found: `media\/none\.png`/);
  const hints = await registered.hints.provideInlayHints(d, new Range(0, 0, 30, 0));
  assert.deepEqual(hints.map((x) => [x.position.line, x.label]), [[7, "= 2p 7 · * 5"]]);
});

test("images pasted or dropped: copied to media/ and referenced", async () => {
  realTabula();
  const root = fs.mkdtempSync(path.join(require("os").tmpdir(), "tabula-img-"));
  fs.mkdirSync(path.join(root, "g", "media"), { recursive: true });
  fs.writeFileSync(path.join(root, "g", "media", "here.png"), "x");
  const outside = path.join(root, "photo.JPG");
  fs.writeFileSync(outside, "jpg");
  vscode.workspace.fs = { readFile: async (u) => fs.readFileSync(u.fsPath) };
  const file = path.join(root, "g", "g.game");
  const text = "# Rules\n\nText.\n\n# Cards {#cards}\n\nGrande marée\n: force:: 2\n  Wave.\n";
  const d = doc(text, file);
  const transfer = (entries) => ({ get: (m) => entries[m] ? { asString: async () => entries[m] } : undefined,
                                   [Symbol.iterator]: function* () { for (const k in entries) yield [k, entries[k]]; } });
  // a pasted image on a card: media/cards/<card>.png, and an image:: field
  const pasted = { "image/png": { asFile: () => ({ name: "image.png", data: async () => new Uint8Array([1, 2]) }) } };
  const [edit] = await registered.paste.provideDocumentPasteEdits(d, [new Range(8, 2, 8, 2)], transfer(pasted));
  assert.equal(edit.insertText, "");
  const create = edit.additionalEdit.ops.find((o) => o.create);
  assert.equal(path.relative(root, create.create.fsPath).split(path.sep).join("/"), "g/media/cards/grande-maree.png");
  assert.deepEqual([...create.contents], [1, 2]);
  assert.equal(edit.additionalEdit.ops.find((o) => o.text).text, "  image:: media/cards/grande-maree.png\n");
  // a file dropped from outside, in the rules: copied to media/, inline image
  const drop = await registered.drop.provideDocumentDropEdits(d, { line: 2, character: 0 }, transfer({ "text/uri-list": "file://" + outside }));
  assert.equal(drop.insertText, "![photo](media/photo.jpg)");
  assert.equal(String(drop.additionalEdit.ops[0].contents), "jpg");
  // a file already in the game's folder: referenced, not copied
  const here = await registered.drop.provideDocumentDropEdits(d, { line: 2, character: 0 }, transfer({ "text/uri-list": "file://" + path.join(root, "g", "media", "here.png") }));
  assert.equal(here.insertText, "![here](media/here.png)");
  assert.equal(here.additionalEdit.ops.length, 0);
  assert.ok(registered.pasteMeta.pasteMimeTypes.includes("image/png"));
});

test("the Tabula panel: games with their status, translations and sheets; the wishlist", async () => {
  realTabula();
  const root = fs.mkdtempSync(path.join(require("os").tmpdir(), "tabula-panel-"));
  const g = path.join(root, "frantic", "frantic.game");
  const list = { vault: root, name: "Jeux", games: [
    { slug: "frantic", title: "Frantic", path: g, players: "2-8", players_note: "2-10 +pandora", duration: "5-45",
      location: "armoire", language: "fr", translations: { en: g.replace(".game", ".en.game") }, sheets: [g.replace(".game", ".sheet")], cover: null },
    { slug: "solo", title: "Solo", path: path.join(root, "solo.game"), players: "1", players_note: "", duration: null,
      location: null, language: "fr", translations: {}, sheets: [], cover: null }] };
  const wish = [{ name: "Pandora", for: "frantic", game: "frantic", priority: 1, price: "15 CHF" }, { name: "Cascadia" },
                { name: "All of Frantic", for: "Frantic", game: "frantic", priority: 2 },
                { name: "Troublemaker", for: "frantic", game: "frantic", in: "All of Frantic" }];
  const fake = path.join(root, "fake-list.js");
  fs.writeFileSync(fake, `const a=process.argv.slice(2);
    if(a.includes('list')) process.stdout.write(${JSON.stringify(JSON.stringify(list))});
    else if(a.includes('wish')) process.stdout.write(${JSON.stringify(JSON.stringify(wish))});
    else if(a.includes('check')) process.stdout.write(JSON.stringify({vault:'', files:[], issues:[]}));
    else process.exit(3);`);
  registered.config = { path: process.execPath, extraArgs: [fake] };
  registered.diags = { [g]: [{ source: "tabula", severity: 1 }] };                 // a warning in frantic.game
  const games = registered.trees["tabula.games"];
  const top = await games.getChildren();
  const items = top.map((x) => games.getTreeItem(x));
  assert.deepEqual(items.map((i) => [i.label, i.description, i.iconPath.id]),
    [["Frantic", "2-8 (2-10 +pandora) players · 5-45 min", "warning"], ["Solo", "1 players", "pass"]]);
  assert.equal(items[0].contextValue, "game-with-sheet");
  assert.equal(items[0].command.arguments[0].fsPath, g);
  const kids = (await games.getChildren(top[0])).map((x) => games.getTreeItem(x));
  assert.deepEqual(kids.map((k) => [k.label, k.iconPath.id]), [["Frantic (en)", "globe"], ["frantic.sheet", "table"]]);
  const wl = registered.trees["tabula.wishlist"];
  const w = (await wl.getChildren()).map((x) => wl.getTreeItem(x));
  assert.deepEqual(w.map((i) => [i.label, i.description, i.iconPath.id]),
    [["Pandora", "for Frantic · 15 CHF", "star-full"], ["All of Frantic", "for Frantic · or separately ↓", "star-half"], ["Cascadia", "", "star-empty"]]);
  const pack = (await wl.getChildren())[1];
  const inPack = (await wl.getChildren(pack)).map((x) => wl.getTreeItem(x));
  assert.deepEqual(inPack.map((i) => [i.label, i.description]), [["Troublemaker", ""]]);
  for (const c of ["tabula.refreshPanel", "tabula.buildSite", "tabula.buildBook", "tabula.printSheet", "tabula.addWish", "tabula.previewGame"]) {
    assert.ok(registered.commands[c], c);
  }
});

test("frontmatter: completes the spec's keys, and the details of an extension", async () => {
  realTabula();
  const text = "---\ntitle: F\npla\nextensions:\n  pandora:\n    description: P\n    ye\n---\n# Rules\n";
  const items = await registered.completion.p.provideCompletionItems(doc(text), { line: 2, character: 3 });
  const keys = items.map((i) => i.label);
  assert.ok(keys.includes("players") && keys.includes("year") && !keys.includes("title"));   // title is already there
  const players = items.find((i) => i.label === "players");
  assert.equal(players.insertText, "players: ");
  assert.match(players.documentation.value, /Player counts/);
  const opt = await registered.completion.p.provideCompletionItems(doc(text), { line: 6, character: 6 });
  assert.deepEqual(opt.map((i) => i.label), ["players", "duration", "year", "needs", "excludes"]);
  assert.equal(opt[0].detail, "extension/variant detail");
  const sheet = await registered.completion.p.provideCompletionItems(doc("---\nsi\n---\n", path.join(baseVault, "g", "g.sheet")), { line: 1, character: 2 });
  assert.ok(sheet.map((i) => i.label).includes("orientation"));
});

test("frontmatter: hover on a key", async () => {
  realTabula();
  const text = "---\nyear: 2018\nbought_at: Spiel\nextensions:\n  p:\n    box: blue\n---\n";
  assert.match((await registered.hover.provideHover(doc(text), { line: 1, character: 1 })).contents.value, /^\*\*year\*\* — The year the game came out/);
  assert.equal((await registered.hover.provideHover(doc(text), { line: 2, character: 3 })).contents.value,
    "**bought_at** — your own key: shown as “Bought at: …” on the game's page and in `tabula show`.");
  assert.match((await registered.hover.provideHover(doc(text), { line: 5, character: 5 })).contents.value, /your own detail/);
});
