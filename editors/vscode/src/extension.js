// Tabula for VS Code. The language server `tabula lsp` (the same parser as every tabula command) answers
// almost everything: problems as you type, completion, hovers, go to definition, references, rename, quick
// fixes, formatting, the outline, folding, links, inline hints and use counts. This file starts it, and adds
// what is VS Code's own: the preview, the Tabula panel, pasted images, checking or formatting the whole vault.
"use strict";

const vscode = require("vscode");
const cp = require("child_process");
const fs = require("fs");
const os = require("os");
const path = require("path");
const core = require("./core");
const sidebar = require("./sidebar");

let diagnostics;                  // "Check the whole vault" (open files: the language server)
let output;
let client = null;                // the language client (tabula lsp)
let vaultUris = new Set();        // uris set by "Check the whole vault"
let warnedMissing = false;

function settings(uri) {
  const c = vscode.workspace.getConfiguration("tabula", uri);
  const folder = uri && vscode.workspace.getWorkspaceFolder(uri);
  const ws = folder ? folder.uri.fsPath : (vscode.workspace.workspaceFolders || [])[0]?.uri.fsPath;
  const x = (v) => core.expand(v, ws, os.homedir());
  return {
    command: x(c.get("path") || "tabula"),
    extraArgs: (c.get("extraArgs") || []).map(x),
    vault: x(c.get("vault") || ""),
    run: c.get("run") || "onType",
    delay: c.get("delay") ?? 500,
    definitions: !!c.get("requireDefinitions"),
    spell: !!c.get("spellCheck"),
    siteFolder: x(c.get("siteFolder") || ""),
    followCursor: c.get("previewFollowsCursor") !== false,
    cwd: ws || (uri ? path.dirname(uri.fsPath) : os.homedir()),
  };
}

function isGame(doc) {
  return doc.languageId === "tabula" && doc.uri.scheme === "file";
}

/**
 * Start tabula. Returns { child, done }: `done` resolves with the parsed JSON, or null when tabula
 * couldn't run, failed, or was cancelled (the reason goes to the Output panel).
 */
function runTabula(args, cfg, input, raw = false) {
  let child;
  try {
    child = cp.spawn(cfg.command, args, { cwd: cfg.cwd, env: { ...process.env, NO_COLOR: "1", PYTHONIOENCODING: "utf-8" } });
  } catch (e) {
    missing(cfg, e);
    return { child: null, done: Promise.resolve(null) };
  }
  const done = new Promise((resolve) => {
    let out = "";
    let err = "";
    child.stdout.on("data", (d) => (out += d));
    child.stderr.on("data", (d) => (err += d));
    let failed = false;
    child.on("error", (e) => {
      failed = true;
      if (e.code === "ENOENT") missing(cfg, e);
      else output.appendLine(`tabula: ${e.message}`);
      resolve(null);
    });
    child.on("close", (code, signal) => {
      if (signal || failed) return resolve(null);          // cancelled by a newer check, or couldn't start
      if (raw) return resolve({ code, out, err });          // the preview: the page itself, or why it failed
      try {
        resolve(core.parseCheckOutput(out));
      } catch (e) {
        output.appendLine(`$ ${cfg.command} ${args.join(" ")}`);
        output.appendLine((err || out || e.message).trim());
        vscode.window.setStatusBarMessage("Tabula: check failed (see Output → Tabula)", 5000);
        resolve(null);
      }
    });
  });
  child.stdin.on("error", () => {});
  child.stdin.end(input !== undefined ? Buffer.from(input, "utf8") : undefined);
  return { child, done };
}

function missing(cfg, e) {
  output.appendLine(`could not run '${cfg.command}': ${e.message}`);
  if (warnedMissing) return;
  warnedMissing = true;
  vscode.window
    .showWarningMessage(
      `Tabula: '${cfg.command}' was not found. Install tabula (pipx install --editable ./cli) or set "tabula.path".`,
      "Open settings"
    )
    .then((pick) => pick && vscode.commands.executeCommand("workbench.action.openSettings", "tabula."));
}

/** Text of a line in a file: from the open editor if there is one, else from the disk. */
const diskCache = new Map();
function lineOf(file, line, openDocs) {
  const doc = openDocs.get(path.resolve(file).toLowerCase());
  if (doc) return line < doc.lineCount ? doc.lineAt(line).text : "";
  if (!diskCache.has(file)) {
    try {
      diskCache.set(file, fs.readFileSync(file, "utf8").replace(/\r\n?/g, "\n").split("\n"));
    } catch {
      diskCache.set(file, []);
    }
  }
  return diskCache.get(file)[line] || "";
}

function toDiagnostics(issues) {
  const openDocs = new Map(vscode.workspace.textDocuments.map((d) => [path.resolve(d.uri.fsPath).toLowerCase(), d]));
  diskCache.clear();
  const byFile = new Map();
  for (const i of issues) {
    const line = Math.max(0, (i.line || 1) - 1);
    const text = lineOf(i.path, line, openDocs);
    const [a, b] = core.issueColumns(text, i.message);
    const d = new vscode.Diagnostic(
      new vscode.Range(line, a, line, Math.max(b, a + 1)),
      i.message,
      core.severity(i.level, vscode.DiagnosticSeverity)
    );
    d.source = "tabula";
    if (!byFile.has(i.path)) byFile.set(i.path, []);
    byFile.get(i.path).push(d);
  }
  return byFile;
}

async function checkVault(opts = {}) {
  const quiet = !!(opts && opts.quiet);         // the panel's first look: no message, no Problems panel
  const editor = vscode.window.activeTextEditor;
  const uri = editor && isGame(editor.document) ? editor.document.uri : (vscode.workspace.workspaceFolders || [])[0]?.uri;
  const cfg = settings(uri);
  const args = core.checkArgs({ vault: cfg.vault, extraArgs: cfg.extraArgs, definitions: cfg.definitions, spell: cfg.spell });
  const result = await vscode.window.withProgress(
    { location: vscode.ProgressLocation.Window, title: "Tabula: checking the vault" },
    () => runTabula(args, cfg).done
  );
  if (!result) return;
  const byFile = toDiagnostics(result.issues);
  for (const u of vaultUris) diagnostics.delete(vscode.Uri.parse(u));
  vaultUris = new Set();
  const open = new Set(vscode.workspace.textDocuments.map((d) => path.resolve(d.uri.fsPath).toLowerCase()));
  for (const [f, list] of byFile) {
    if (open.has(path.resolve(f).toLowerCase())) continue;       // the language server already shows those
    const u = vscode.Uri.file(f);
    diagnostics.set(u, list);
    vaultUris.add(u.toString());
  }
  const errors = result.issues.filter((i) => i.level === "error").length;
  const warnings = result.issues.filter((i) => i.level === "warning").length;
  if (quiet) return;
  vscode.window.showInformationMessage(
    errors || warnings ? `Tabula: ${errors} error(s), ${warnings} warning(s) in ${result.vault}` : `Tabula: no problems in ${result.vault}`
  );
  if (errors || warnings) vscode.commands.executeCommand("workbench.actions.view.problems");
}

// ------------------------------------------------------------------ the language server (tabula lsp)

let lsp = null;                   // the vscode-languageclient module, loaded when the server starts

function loadClient() {
  if (!lsp) lsp = require("vscode-languageclient/node");
  return lsp;
}

/** What starts `tabula lsp`, from the settings. */
function serverOptions(cfg) {
  const args = [...cfg.extraArgs];
  if (cfg.vault) args.push("--vault", cfg.vault);
  args.push("lsp");
  return { command: cfg.command, args, options: { cwd: cfg.cwd, env: { ...process.env, NO_COLOR: "1", PYTHONIOENCODING: "utf-8" } } };
}

async function startClient() {
  const ws = (vscode.workspace.workspaceFolders || [])[0];
  const cfg = settings(ws && ws.uri);
  const { LanguageClient } = loadClient();
  client = new LanguageClient("tabula", "Tabula", serverOptions(cfg), {
    documentSelector: [{ scheme: "file", language: "tabula" }],
    outputChannel: output,
    markdown: { supportHtml: true, isTrusted: false },      // card pictures in hovers are <img> tags
    initializationOptions: { spell: cfg.spell, definitions: cfg.definitions, images: "html" },
  });
  try {
    await client.start();
  } catch (e) {
    client = null;
    output.appendLine(`could not start '${cfg.command} lsp': ${e && e.message}`);
    if (!warnedMissing) {
      warnedMissing = true;
      vscode.window.showWarningMessage(
        "Tabula: the language server didn't start. It needs tabula 0.33 with pygls (pipx install ./cli, then pipx inject tabula pygls); see Output → Tabula.",
        "Open settings"
      ).then((pick) => pick && vscode.commands.executeCommand("workbench.action.openSettings", "tabula."));
    }
  }
}

async function restartClient() {
  const old = client;
  client = null;
  if (old) {
    try {
      await old.stop();
    } catch { /* already gone */ }
  }
  await startClient();
}

/** The outline of an open document, from the language server (null when it isn't running). */
async function outlineOf(doc) {
  if (!client) return null;
  try {
    return await client.sendRequest("tabula/outline", { uri: doc.uri.toString() });
  } catch {
    return null;
  }
}

/** The code lenses' "used N times": show those places (the server sends plain JSON). */
function showReferences(uri, position, locations) {
  const c = client && client.protocol2CodeConverter;
  if (!c) return;
  vscode.commands.executeCommand("editor.action.showReferences", c.asUri(uri), c.asPosition(position),
                                 (locations || []).map((l) => c.asLocation(l)));
}

// ------------------------------------------------------------------ files of the vault

/** The vault folder of a file: the nearest folder above it with _shared/ or vault.yaml. */
function vaultRoot(file) {
  let dir = path.dirname(file);
  for (let i = 0; i < 12; i++) {
    if (path.basename(dir) === "_shared") return path.dirname(dir);
    if (fs.existsSync(path.join(dir, "_shared")) || fs.existsSync(path.join(dir, "vault.yaml"))) return dir;
    const up = path.dirname(dir);
    if (up === dir) break;
    dir = up;
  }
  return path.dirname(path.dirname(file));
}

// ------------------------------------------------------------------ preview

let preview = null;              // { panel, doc, child, timer }

function previewDocument(doc) {
  if (!preview || !isGame(doc)) return;
  preview.doc = doc;
  preview.panel.title = `Preview: ${path.basename(doc.uri.fsPath)}`;
  if (path.basename(path.dirname(doc.uri.fsPath)) === "_shared") {
    preview.panel.webview.html = message("A shared fragment is shown in the games that include it (open one of them).");
    return;
  }
  const cfg = settings(doc.uri);
  if (preview.child && preview.child.exitCode === null) preview.child.kill();
  const args = core.previewArgs({ file: doc.uri.fsPath, vault: cfg.vault, extraArgs: cfg.extraArgs });
  const { child, done } = runTabula(args, cfg, doc.getText(), true);
  preview.child = child;
  done.then((r) => {
    if (!preview || preview.child !== child || !r) return;
    if (r.code !== 0) {
      preview.panel.webview.html = message(`tabula couldn't render this file:\n\n${(r.err || r.out).trim()}`);
      return;
    }
    const nonce = Array.from({ length: 24 }, () => Math.floor(Math.random() * 36).toString(36)).join("");
    preview.panel.webview.html = core.previewHtml(r.out, nonce, preview.panel.webview.cspSource);
  });
}

function message(text) {
  const esc = text.replace(/&/g, "&amp;").replace(/</g, "&lt;");
  return `<!doctype html><html><body style="font-family:sans-serif;padding:2rem;white-space:pre-wrap">${esc}</body></html>`;
}

function schedulePreview(doc, delay) {
  if (!preview || !isGame(doc) || (preview.doc && doc.uri.toString() !== preview.doc.uri.toString())) return;
  clearTimeout(preview.timer);
  preview.timer = setTimeout(() => previewDocument(doc), delay);
}

function openPreview() {
  const ed = vscode.window.activeTextEditor;
  if (!ed || !isGame(ed.document)) {
    vscode.window.showInformationMessage("Tabula: open a .game file to preview it.");
    return;
  }
  if (preview) {
    preview.panel.reveal(vscode.ViewColumn.Beside, true);
    previewDocument(ed.document);
    return;
  }
  const panel = vscode.window.createWebviewPanel("tabulaPreview", "Preview", { viewColumn: vscode.ViewColumn.Beside, preserveFocus: true },
                                                 { enableScripts: true, localResourceRoots: [] });
  preview = { panel, doc: null, child: null, timer: null };
  panel.onDidDispose(() => {
    if (preview && preview.child && preview.child.exitCode === null) preview.child.kill();
    preview = null;
  });
  panel.webview.onDidReceiveMessage((msg) => {
    if (msg && typeof msg.line === "number" && preview && preview.doc) {   // double-click in the preview
      const line = Math.max(0, Math.min(msg.line - 1, preview.doc.lineCount - 1));
      vscode.window.showTextDocument(preview.doc, { viewColumn: vscode.ViewColumn.One, preserveFocus: false }).then((ed) => {
        const pos = new vscode.Position(line, 0);
        ed.selection = new vscode.Selection(pos, pos);
        ed.revealRange(new vscode.Range(pos, pos), vscode.TextEditorRevealType.InCenterIfOutsideViewport);
      });
      return;
    }
    const target = msg && msg.open ? core.previewLink(msg.open) : null;
    if (!target) return;
    if (target.url) vscode.env.openExternal(vscode.Uri.parse(target.url));
    if (target.game && preview && preview.doc) {
      const root = vaultRoot(preview.doc.uri.fsPath);
      const file = [path.join(root, target.game, `${target.game}.game`), path.join(root, `${target.game}.game`)]
        .find((f) => fs.existsSync(f));
      if (file) vscode.window.showTextDocument(vscode.Uri.file(file), { viewColumn: vscode.ViewColumn.One });
    }
  });
  previewDocument(ed.document);
}

// ------------------------------------------------------------------ images pasted or dropped

const MIME_EXT = { "image/png": ".png", "image/jpeg": ".jpg", "image/gif": ".gif", "image/webp": ".webp", "image/svg+xml": ".svg" };
const IMAGE_FILE = /\.(png|jpe?g|gif|webp|svg)$/i;

/** The image of a paste or drop: { data } (pasted bytes) or { src } (a file), with its extension and name. */
async function droppedImage(dataTransfer) {
  const list = dataTransfer.get("text/uri-list");
  if (list) {
    for (const line of (await list.asString()).split(/\r?\n/)) {
      if (!line.trim() || line.startsWith("#")) continue;
      const uri = vscode.Uri.parse(line.trim());
      if (uri.scheme === "file" && IMAGE_FILE.test(uri.fsPath)) {
        return { src: uri, ext: path.extname(uri.fsPath).toLowerCase(), name: path.basename(uri.fsPath, path.extname(uri.fsPath)) };
      }
    }
  }
  for (const [mime, item] of dataTransfer) {
    if (!MIME_EXT[mime]) continue;
    const file = item.asFile && item.asFile();
    if (!file) continue;
    return { data: await file.data(), ext: MIME_EXT[mime], name: file.name ? path.basename(file.name, path.extname(file.name)) : "image" };
  }
  return null;
}

/**
 * What a pasted or dropped image does: copied to media/ (media/cards/ on a card) unless it's already in the
 * game's folder, then referenced (image:: on a card, ![…](…) elsewhere). Returns { insertText, additionalEdit }.
 */
async function imageEdit(doc, line, dataTransfer) {
  const img = await droppedImage(dataTransfer);
  if (!img) return null;
  const dir = path.dirname(doc.uri.fsPath);
  const o = (await outlineOf(doc)) || { definitions: [] };   // from the language server
  const lines = doc.getText().replace(/\r\n?/g, "\n").split("\n");
  const probe = core.imagePlacement(o, lines, line, "x");
  const folder = path.join(dir, "media", probe.kind === "card" ? "cards" : "");
  const we = new vscode.WorkspaceEdit();
  let file;
  if (img.src && !path.relative(dir, img.src.fsPath).startsWith("..")) {
    file = img.src.fsPath;                                    // already in the game's folder: just refer to it
  } else {
    let existing = [];
    try {
      existing = fs.readdirSync(folder);
    } catch { /* the folder is created with the file */ }
    file = path.join(folder, core.imageFileName(probe.kind === "card" ? probe.term : img.name, img.ext, existing));
    const contents = img.data || (await vscode.workspace.fs.readFile(img.src));
    we.createFile(vscode.Uri.file(file), { contents, ignoreIfExists: false });
  }
  const rel = path.relative(dir, file).split(path.sep).join("/");
  const place = core.imagePlacement(o, lines, line, rel, probe.kind === "card" ? "" : img.name);
  if (place.kind === "inline") return { insertText: place.text, additionalEdit: we };
  for (const e of place.edits) {
    if (e.line >= doc.lineCount) we.insert(doc.uri, new vscode.Position(doc.lineCount, 0), e.text);
    else we.replace(doc.uri, new vscode.Range(e.line, e.start, e.line, e.end), e.text);
  }
  return { insertText: "", additionalEdit: we };
}

const dropProvider = {
  async provideDocumentDropEdits(doc, pos, dataTransfer) {
    const r = await imageEdit(doc, pos.line, dataTransfer);
    if (!r) return undefined;
    const edit = new vscode.DocumentDropEdit(r.insertText);
    edit.additionalEdit = r.additionalEdit;
    return edit;
  },
};

const pasteProvider = {
  async provideDocumentPasteEdits(doc, ranges, dataTransfer) {
    const r = await imageEdit(doc, ranges[0].start.line, dataTransfer);
    if (!r) return undefined;
    const kind = vscode.DocumentDropOrPasteEditKind ? vscode.DocumentDropOrPasteEditKind.Empty.append("tabula", "image") : undefined;
    const edit = new vscode.DocumentPasteEdit(r.insertText, "Insert the image (Tabula)", kind);
    edit.additionalEdit = r.additionalEdit;
    return [edit];
  },
};

async function formatVault() {
  const editor = vscode.window.activeTextEditor;
  const uri = editor && isGame(editor.document) ? editor.document.uri : (vscode.workspace.workspaceFolders || [])[0]?.uri;
  const cfg = settings(uri);
  const r = await vscode.window.withProgress(
    { location: vscode.ProgressLocation.Window, title: "Tabula: formatting the vault" },
    () => runTabula(core.fmtArgs({ vault: cfg.vault, extraArgs: cfg.extraArgs }), cfg, undefined, true).done
  );
  if (!r) return;
  output.appendLine(`$ tabula fmt\n${(r.out + r.err).trim()}`);
  const summary = r.out.trim().split("\n").pop() || r.err.trim();
  if (r.code === 0) vscode.window.showInformationMessage(`Tabula: ${summary}`);
  else vscode.window.showWarningMessage(`Tabula: ${summary}`);
}

// ------------------------------------------------------------------ activation

function activate(context) {
  diagnostics = vscode.languages.createDiagnosticCollection("tabula-vault");
  output = vscode.window.createOutputChannel("Tabula");
  const sel = { language: "tabula", scheme: "file" };
  context.subscriptions.push(
    diagnostics,
    output,
    ...(vscode.languages.registerDocumentDropEditProvider
      ? [vscode.languages.registerDocumentDropEditProvider(sel, dropProvider)] : []),
    ...(vscode.languages.registerDocumentPasteEditProvider
      ? [vscode.languages.registerDocumentPasteEditProvider(sel, pasteProvider, {
          providedPasteEditKinds: vscode.DocumentDropOrPasteEditKind ? [vscode.DocumentDropOrPasteEditKind.Empty.append("tabula", "image")] : [],
          pasteMimeTypes: ["image/png", "image/jpeg", "image/gif", "image/webp", "text/uri-list"],
        })] : []),
    vscode.commands.registerCommand("tabula.showReferences", showReferences),
    vscode.commands.registerCommand("tabula.formatFile", () => vscode.commands.executeCommand("editor.action.formatDocument")),
    vscode.commands.registerCommand("tabula.formatVault", formatVault),
    vscode.commands.registerCommand("tabula.checkVault", () => checkVault()),
    vscode.commands.registerCommand("tabula.checkFile", () => checkVault()),
    vscode.commands.registerCommand("tabula.restartServer", restartClient),
    vscode.commands.registerCommand("tabula.openPreview", openPreview),
    vscode.window.onDidChangeActiveTextEditor((ed) => { if (ed && preview && isGame(ed.document)) previewDocument(ed.document); }),
    vscode.window.onDidChangeTextEditorSelection((e) => {          // the preview follows the cursor
      if (!preview || e.textEditor.document !== preview.doc || !settings(preview.doc.uri).followCursor) return;
      clearTimeout(preview.cursorTimer);
      const line = e.selections[0].active.line + 1;
      preview.cursorTimer = setTimeout(() => preview && preview.panel.webview.postMessage({ line }), 120);
    }),
    vscode.workspace.onDidSaveTextDocument((doc) => schedulePreview(doc, 0)),
    vscode.workspace.onDidChangeTextDocument((e) => {
      if (e.contentChanges.length) schedulePreview(e.document, settings(e.document.uri).delay);
    }),
    vscode.workspace.onDidChangeConfiguration((e) => {
      if (!e.affectsConfiguration("tabula")) return;
      warnedMissing = false;
      restartClient();
    }),
    { dispose: () => client && client.stop() }
  );
  sidebar.register(context, { runTabula, settings, checkVault });
  return startClient();
}

function deactivate() {
  return client ? client.stop() : undefined;
}

module.exports = { activate, deactivate };
