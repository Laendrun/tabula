"use strict";
// The extension, run against minimal stand-ins for the VS Code API and for vscode-languageclient
// (the language features themselves are tested with the server, in tests/test_lsp.py).
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
    createOutputChannel: (name, opts) => {
      const ch = { name, opts, appendLine() {}, dispose() {} };
      if (opts && opts.log) Object.assign(ch, { logLevel: 2, onDidChangeLogLevel: () => disposable, info() {}, warn() {}, error() {} });
      return ch;
    },
    onDidChangeActiveTextEditor: () => disposable,
    registerTreeDataProvider: (id, p) => { (registered.trees = registered.trees || {})[id] = p; return disposable; },
    withProgress: (o, f) => f(),
    onDidChangeTextEditorSelection: (f) => { registered.onSelection = f; return disposable; },
    showTextDocument: (doc) => { const ed = { document: doc, revealRange(r) { ed.revealed = r; } }; registered.shown = ed; return Promise.resolve(ed); },
    activeTextEditor: null,
    setStatusBarMessage() {},
    showInformationMessage() {},
    showWarningMessage: (m) => { (registered.warnings = registered.warnings || []).push(m); return Promise.resolve(); },
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
  commands: { registerCommand: (name, f) => { (registered.commands = registered.commands || {})[name] = f; return disposable; },
              executeCommand: (name, ...args) => { (registered.executed = registered.executed || []).push([name, ...args]); return Promise.resolve(); } },
  workspace: {
    getConfiguration: () => ({ get: (k) => registered.config && registered.config[k] }),
    getWorkspaceFolder: () => null,
    workspaceFolders: [],
    textDocuments: [],
    onDidOpenTextDocument: () => disposable, onDidSaveTextDocument: () => disposable,
    onDidChangeTextDocument: () => disposable, onDidCloseTextDocument: () => disposable,
    onDidChangeConfiguration: (f) => { registered.onConfig = f; return disposable; },
  },
};
// vscode-languageclient: records how the server is started, answers requests with registered.lspAnswer
class LanguageClient {
  constructor(id, name, server, options) {
    Object.assign(this, { id, name, server, options, stopped: false });
    (registered.clients = registered.clients || []).push(this);
    this.protocol2CodeConverter = {
      asUri: (u) => vscode.Uri.parse(u),
      asPosition: (p) => new Position(p.line, p.character),
      asLocation: (l) => new Location(vscode.Uri.parse(l.uri), new Range(l.range.start.line, l.range.start.character, l.range.end.line, l.range.end.character)),
    };
  }
  start() { return registered.startFails ? Promise.reject(new Error("spawn tabula ENOENT")) : Promise.resolve(); }
  stop() { this.stopped = true; return Promise.resolve(); }
  sendRequest(method, params) { return Promise.resolve(registered.lspAnswer ? registered.lspAnswer(method, params) : null); }
}
const load = Module._load;
Module._load = function (request, ...rest) {
  if (request === "vscode") return vscode;
  if (request === "vscode-languageclient/node") return { LanguageClient };
  return load.call(this, request, ...rest);
};
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

const activated = require("../src/extension").activate({ subscriptions: [] });

function doc(text, file = DEFAULT_FILE) {
  const lines = text.split("\n");
  return { getText: () => text, lineAt: (i) => ({ text: lines[i] }), languageId: "tabula", lineCount: lines.length,
           uri: { fsPath: file, scheme: "file", toString: () => "file://" + file } };
}
const TEXT = "# Setup {#setup}\n\n- 1x [[Deck]]\n\nRead [[#\nUse the [[de\nUse the [[de]] now\n\n# Glossary\n\nDeck\n: points:: 2\n  52 cards.\n";

const vaultDir = fs.mkdtempSync(path.join(os.tmpdir(), "tabula-vault-"));
fs.mkdirSync(path.join(vaultDir, "g"));
const GAME_FILE = path.join(vaultDir, "g", "g.game");

/** What the language server answers to tabula/outline: the real `tabula outline` of a file's text. */
function serverOutline(file, text) {
  const out = require("child_process").execFileSync(PYTHON, ["-m", "tabula", "outline", file, "--json", "--stdin"],
    { input: text, env: process.env });
  return JSON.parse(out.toString("utf8"));
}

test("the language server: tabula lsp, started with the settings", async () => {
  await activated;
  const c = registered.clients[0];
  assert.equal(c.id, "tabula");
  assert.equal(c.server.command, PYTHON);
  assert.deepEqual(c.server.args, ["-m", "tabula", "lsp"]);
  assert.deepEqual(c.options.documentSelector, [{ scheme: "file", language: "tabula" }]);
  assert.deepEqual(c.options.initializationOptions, { spell: false, definitions: false, images: "html" });
  assert.equal(c.options.markdown.supportHtml, true);
  assert.equal(typeof c.options.outputChannel.onDidChangeLogLevel, "function");     // the client needs a log channel
  // a setting changes: the server restarts with it
  registered.config = { path: PYTHON, extraArgs: ["-m", "tabula"], spellCheck: true, vault: "/v" };
  await registered.onConfig({ affectsConfiguration: (k) => k === "tabula" });
  await new Promise((r) => setTimeout(r, 10));
  const d = registered.clients[registered.clients.length - 1];
  assert.equal(c.stopped, true);
  assert.deepEqual(d.server.args, ["-m", "tabula", "--vault", "/v", "lsp"]);
  assert.equal(d.options.initializationOptions.spell, true);
  realTabula();
  await registered.commands["tabula.restartServer"]();
});

test("a server that doesn't start: one message, how to install it", async () => {
  registered.startFails = true;
  registered.warnings = [];
  await registered.commands["tabula.restartServer"]();
  await registered.commands["tabula.restartServer"]();
  assert.equal(registered.warnings.length, 1);
  assert.match(registered.warnings[0], /pipx inject tabula pygls/);
  registered.startFails = false;
  await registered.commands["tabula.restartServer"]();
});

test("used N times: the server's locations become VS Code's", async () => {
  registered.executed = [];
  const loc = { uri: "file:///v/g.game", range: { start: { line: 3, character: 2 }, end: { line: 3, character: 9 } } };
  registered.commands["tabula.showReferences"]("file:///v/g.game", { line: 7, character: 0 }, [loc]);
  const [name, uri, pos, locs] = registered.executed.pop();
  assert.equal(name, "editor.action.showReferences");
  assert.equal(uri.fsPath, "/v/g.game");
  assert.deepEqual([pos.line, locs[0].range.start.character], [7, 2]);
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
  registered.lspAnswer = (method, params) => (method === "tabula/outline" && params.uri === d.uri.toString() ? serverOutline(file, text) : null);
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

