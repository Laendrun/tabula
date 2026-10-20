// Tabula for VS Code: runs `tabula check` while you write and shows the results as squiggles.
"use strict";

const vscode = require("vscode");
const cp = require("child_process");
const fs = require("fs");
const os = require("os");
const path = require("path");
const core = require("./core");

let diagnostics;
let output;
const running = new Map();        // document uri -> child process (one check at a time per file)
const timers = new Map();         // document uri -> debounce timer
const owned = new Map();          // file checked -> uris it set diagnostics on (to clear them next time)
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
function runTabula(args, cfg, input) {
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
      i.level === "error" ? vscode.DiagnosticSeverity.Error : vscode.DiagnosticSeverity.Warning
    );
    d.source = "tabula";
    if (!byFile.has(i.path)) byFile.set(i.path, []);
    byFile.get(i.path).push(d);
  }
  return byFile;
}

async function checkDocument(doc) {
  if (!isGame(doc)) return;
  const key = doc.uri.toString();
  const cfg = settings(doc.uri);
  const prev = running.get(key);
  if (prev && prev.exitCode === null) prev.kill();
  const args = core.checkArgs({
    file: doc.uri.fsPath, vault: cfg.vault, extraArgs: cfg.extraArgs, definitions: cfg.definitions, stdin: true,
  });
  const { child, done } = runTabula(args, cfg, doc.getText());
  running.set(key, child);
  const result = await done;
  if (running.get(key) !== child || !result) return;      // a newer check is on its way, or this one failed
  running.delete(key);

  const byFile = toDiagnostics(result.issues);
  const touched = new Set();
  for (const f of [...result.files, doc.uri.fsPath, ...byFile.keys()]) {
    const uri = vscode.Uri.file(f);
    diagnostics.set(uri, byFile.get(f) || []);
    touched.add(uri.toString());
  }
  for (const u of owned.get(key) || []) {
    if (!touched.has(u)) diagnostics.delete(vscode.Uri.parse(u));
  }
  owned.set(key, touched);
}

function schedule(doc, delay) {
  if (!isGame(doc)) return;
  const key = doc.uri.toString();
  clearTimeout(timers.get(key));
  timers.set(key, setTimeout(() => {
    timers.delete(key);
    checkDocument(doc);
  }, delay));
}

async function checkVault() {
  const editor = vscode.window.activeTextEditor;
  const uri = editor && isGame(editor.document) ? editor.document.uri : (vscode.workspace.workspaceFolders || [])[0]?.uri;
  const cfg = settings(uri);
  const args = core.checkArgs({ vault: cfg.vault, extraArgs: cfg.extraArgs, definitions: cfg.definitions });
  const result = await vscode.window.withProgress(
    { location: vscode.ProgressLocation.Window, title: "Tabula: checking the vault" },
    () => runTabula(args, cfg).done
  );
  if (!result) return;
  const byFile = toDiagnostics(result.issues);
  for (const u of vaultUris) diagnostics.delete(vscode.Uri.parse(u));
  vaultUris = new Set();
  for (const [f, list] of byFile) {
    const u = vscode.Uri.file(f);
    diagnostics.set(u, list);
    vaultUris.add(u.toString());
  }
  const errors = result.issues.filter((i) => i.level === "error").length;
  const warnings = result.issues.length - errors;
  vscode.window.showInformationMessage(
    errors || warnings ? `Tabula: ${errors} error(s), ${warnings} warning(s) in ${result.vault}` : `Tabula: no problems in ${result.vault}`
  );
  if (errors || warnings) vscode.commands.executeCommand("workbench.actions.view.problems");
}

// ------------------------------------------------------------------ outline, folding, go to definition

const symbols = {
  provideDocumentSymbols(doc) {
    const o = core.outline(doc.getText());
    const root = [];
    const stack = [];
    const range = (a, b) => new vscode.Range(a, 0, b, doc.lineAt(Math.min(b, doc.lineCount - 1)).text.length);
    for (const h of o.headings) {
      const s = new vscode.DocumentSymbol(
        (h.key ? "★ " : "") + (h.title || "(untitled)"), h.attrs ? `{${h.attrs}}` : "", vscode.SymbolKind.Namespace,
        range(h.line, h.end), range(h.line, h.line)
      );
      while (stack.length && stack[stack.length - 1].level >= h.level) stack.pop();
      (stack.length ? stack[stack.length - 1].sym.children : root).push(s);
      stack.push({ level: h.level, end: h.end, sym: s });
    }
    const parentAt = (line) => {
      let best = null;
      const walk = (list) => {
        for (const s of list) {
          if (s.range.start.line <= line && line <= s.range.end.line) {
            best = s;
            walk(s.children);
          }
        }
      };
      walk(root);
      return best ? best.children : root;
    };
    for (const d of o.definitions) {
      parentAt(d.line).push(new vscode.DocumentSymbol(
        d.term, d.cond ? `{${d.cond}}` : "", vscode.SymbolKind.Field, range(d.line, d.end), range(d.line, d.line)
      ));
    }
    for (const c of o.components) {
      parentAt(c.line).push(new vscode.DocumentSymbol(
        c.name, `${c.quantity}x`, vscode.SymbolKind.Constant, range(c.line, c.line), range(c.line, c.line)
      ));
    }
    const sort = (list) => {
      list.sort((a, b) => a.range.start.line - b.range.start.line);
      list.forEach((s) => sort(s.children));
    };
    sort(root);
    return root;
  },
};

const folding = {
  provideFoldingRanges(doc) {
    const o = core.outline(doc.getText());
    return [...o.headings, ...o.definitions.map((d) => ({ line: d.line, end: d.end }))]
      .filter((x) => x.end > x.line)
      .map((x) => new vscode.FoldingRange(x.line, x.end));
  },
};

const definitionProvider = {
  provideDefinition(doc, pos) {
    const ref = core.refAt(doc.lineAt(pos.line).text, pos.character);
    if (!ref) return null;
    const files = [doc.uri.fsPath];
    // in a translation, terms may only exist in the default-language file: look there too
    const m = path.basename(doc.uri.fsPath).match(/^(.*)\.([a-z]{2}(?:-[A-Za-z]{2})?)\.game$/);
    if (m) files.push(path.join(path.dirname(doc.uri.fsPath), `${m[1]}.game`));
    for (const f of files) {
      let text;
      try {
        text = f === doc.uri.fsPath ? doc.getText() : fs.readFileSync(f, "utf8");
      } catch {
        continue;
      }
      const lines = core.findTargets(text, ref.name);
      if (lines.length) return lines.map((l) => new vscode.Location(vscode.Uri.file(f), new vscode.Position(l, 0)));
    }
    return null;
  },
};

// ------------------------------------------------------------------ activation

function activate(context) {
  diagnostics = vscode.languages.createDiagnosticCollection("tabula");
  output = vscode.window.createOutputChannel("Tabula");
  const sel = { language: "tabula", scheme: "file" };
  context.subscriptions.push(
    diagnostics,
    output,
    vscode.languages.registerDocumentSymbolProvider(sel, symbols),
    vscode.languages.registerFoldingRangeProvider(sel, folding),
    vscode.languages.registerDefinitionProvider(sel, definitionProvider),
    vscode.commands.registerCommand("tabula.checkVault", checkVault),
    vscode.commands.registerCommand("tabula.checkFile", () => {
      const ed = vscode.window.activeTextEditor;
      if (ed) checkDocument(ed.document);
    }),
    vscode.workspace.onDidOpenTextDocument((doc) => schedule(doc, 0)),
    vscode.workspace.onDidSaveTextDocument((doc) => schedule(doc, 0)),
    vscode.workspace.onDidChangeTextDocument((e) => {
      const cfg = settings(e.document.uri);
      if (cfg.run === "onType" && e.contentChanges.length) schedule(e.document, cfg.delay);
    }),
    vscode.workspace.onDidCloseTextDocument((doc) => {
      const key = doc.uri.toString();
      clearTimeout(timers.get(key));
      if (!vaultUris.has(key)) diagnostics.delete(doc.uri);
    }),
    vscode.workspace.onDidChangeConfiguration((e) => {
      if (!e.affectsConfiguration("tabula")) return;
      warnedMissing = false;
      vscode.workspace.textDocuments.forEach((d) => schedule(d, 0));
    })
  );
  vscode.workspace.textDocuments.forEach((d) => schedule(d, 0));
}

function deactivate() {
  for (const t of timers.values()) clearTimeout(t);
  for (const c of running.values()) if (c && c.exitCode === null) c.kill();
}

module.exports = { activate, deactivate };
