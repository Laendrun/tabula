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
    spell: !!c.get("spellCheck"),
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

async function checkDocument(doc) {
  if (!isGame(doc)) return;
  const key = doc.uri.toString();
  const cfg = settings(doc.uri);
  const prev = running.get(key);
  if (prev && prev.exitCode === null) prev.kill();
  const args = core.checkArgs({
    file: doc.uri.fsPath, vault: cfg.vault, extraArgs: cfg.extraArgs, definitions: cfg.definitions, spell: cfg.spell, stdin: true,
  });
  const { child, done } = runTabula(args, cfg, doc.getText());
  running.set(key, child);
  const result = await done;
  if (running.get(key) !== child || !result) return;      // a newer check is on its way, or this one failed
  running.delete(key);
  if (result.vault) vaults.set(key, result.vault);

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
  const args = core.checkArgs({ vault: cfg.vault, extraArgs: cfg.extraArgs, definitions: cfg.definitions, spell: cfg.spell });
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
    const inc = core.includeAt(doc.lineAt(pos.line).text, pos.character);
    if (inc) {
      const file = fragmentFile(doc.uri.fsPath, inc.name);
      if (!file) return null;
      const line = inc.section ? (core.findTargets(readText(file) || "", "#" + inc.section)[0] || 0) : 0;
      return new vscode.Location(vscode.Uri.file(file), new vscode.Position(line, 0));
    }
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
    const inFragments = fragmentTargets(doc, ref.name);
    return inFragments.length ? inFragments : null;
  },
};

// ------------------------------------------------------------------ completion and hover

const KINDS = {
  definition: vscode.CompletionItemKind.Reference,
  component: vscode.CompletionItemKind.Constant,
  section: vscode.CompletionItemKind.Module,
  role: vscode.CompletionItemKind.Keyword,
};

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

/** The language code of a translation file (slug.fr.game), or null. */
function fileLang(file) {
  const m = path.basename(file).match(/^.*\.([a-z]{2}(?:-[A-Za-z]{2})?)\.game$/);
  return m ? m[1] : null;
}

/** _shared/<name>.<lang>.game when the document is a translation and it exists, else _shared/<name>.game. */
function fragmentFile(docFile, name) {
  const dir = path.join(vaultRoot(docFile), "_shared");
  const lang = fileLang(docFile);
  const cands = (lang ? [path.join(dir, `${name}.${lang}.game`)] : []).concat(path.join(dir, `${name}.game`));
  return cands.find((f) => fs.existsSync(f)) || null;
}

function fragmentNames(docFile) {
  try {
    return fs.readdirSync(path.join(vaultRoot(docFile), "_shared"))
      .filter((f) => f.endsWith(".game") && !/\.[a-z]{2}(?:-[A-Za-z]{2})?\.game$/.test(f))
      .map((f) => f.slice(0, -5)).sort();
  } catch {
    return [];
  }
}

function readText(file) {
  try {
    return fs.readFileSync(file, "utf8");
  } catch {
    return null;
  }
}

/** The document with its `![[fragment]]` lines replaced by what they include. */
function expandedText(doc) {
  return core.expandIncludes(doc.getText(), (name) => {
    const file = fragmentFile(doc.uri.fsPath, name);
    return file ? readText(file) : null;
  });
}

/** Terms defined in the fragments a document includes: their locations in the fragment files. */
function fragmentTargets(doc, name) {
  const out = [];
  const seen = new Set();
  for (const line of doc.getText().split(/\r?\n/)) {
    const inc = core.includeAt(line, line.indexOf("!"));
    if (!inc) continue;
    const file = fragmentFile(doc.uri.fsPath, inc.name);
    if (!file || seen.has(file)) continue;
    seen.add(file);
    const text = readText(file) || "";
    for (const l of core.findTargets(text, name)) out.push(new vscode.Location(vscode.Uri.file(file), new vscode.Position(l, 0)));
  }
  return out;
}

function includeCompletions(doc, pos, ctx) {
  const range = new vscode.Range(pos.line, ctx.start, pos.line, pos.character);
  const end = ctx.closed ? "" : "]]";
  if (ctx.section === null) {
    return fragmentNames(doc.uri.fsPath).map((name) => {
      const item = new vscode.CompletionItem({ label: name, description: "_shared" }, vscode.CompletionItemKind.File);
      Object.assign(item, { range, insertText: name + end, filterText: name, detail: "shared fragment" });
      return item;
    });
  }
  const file = fragmentFile(doc.uri.fsPath, ctx.name);
  const text = file && readText(file);
  if (!text) return undefined;
  return core.completions(text).sections.map((x, i) => {
    const item = new vscode.CompletionItem({ label: x.label, description: x.detail }, KINDS[x.kind]);
    Object.assign(item, { range, insertText: x.label + end, filterText: x.label, sortText: String(i).padStart(5, "0"),
                          detail: `${x.kind} in ${ctx.name}` });
    return item;
  });
}

const completionProvider = {
  provideCompletionItems(doc, pos) {
    const inc = core.includeContext(doc.lineAt(pos.line).text, pos.character);
    if (inc) return includeCompletions(doc, pos, inc);
    const ctx = core.completionContext(doc.lineAt(pos.line).text, pos.character);
    if (!ctx) return undefined;
    const all = core.completions(expandedText(doc));
    const list = ctx.section ? all.sections : all.terms;
    const range = new vscode.Range(pos.line, ctx.start, pos.line, pos.character);
    return list.map((x, i) => {
      const item = new vscode.CompletionItem({ label: x.label, description: x.detail }, KINDS[x.kind]);
      item.range = range;
      item.insertText = x.label + (ctx.closed ? "" : "]]");
      item.filterText = x.label;
      item.sortText = String(i).padStart(5, "0");          // definitions first, then components, in file order
      item.detail = x.kind === "role" ? `role ${x.detail}` : x.kind;
      if (x.doc) item.documentation = new vscode.MarkdownString(x.doc);
      return item;
    });
  },
};

const hoverProvider = {
  provideHover(doc, pos) {
    const inc = core.includeAt(doc.lineAt(pos.line).text, pos.character);
    if (inc) {
      const file = fragmentFile(doc.uri.fsPath, inc.name);
      const text = file ? readText(file) : null;
      const md = text ? core.includeHover(text, inc.name, inc.section)
        : `No shared fragment \`${inc.name}\` (looked for _shared/${inc.name}.game)`;
      if (!md) return null;
      return new vscode.Hover(new vscode.MarkdownString(md), new vscode.Range(pos.line, inc.start, pos.line, inc.end));
    }
    const ref = core.refAt(doc.lineAt(pos.line).text, pos.character);
    if (!ref) return null;
    let text = core.hoverText(expandedText(doc), ref.name);
    // in a translation, terms may only be defined in the default-language file
    const m = path.basename(doc.uri.fsPath).match(/^(.*)\.([a-z]{2}(?:-[A-Za-z]{2})?)\.game$/);
    if (!text && m) {
      try {
        text = core.hoverText(fs.readFileSync(path.join(path.dirname(doc.uri.fsPath), `${m[1]}.game`), "utf8"), ref.name);
      } catch {
        text = null;
      }
    }
    if (!text) return null;
    const range = new vscode.Range(pos.line, ref.start, pos.line, ref.end);
    return new vscode.Hover(new vscode.MarkdownString(text), range);
  },
};

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
  const args = [...cfg.extraArgs, ...(cfg.vault ? ["--vault", cfg.vault] : []),
                "export", doc.uri.fsPath, "--interactive", "--stdin", "-o", "-"];
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

// ------------------------------------------------------------------ quick fixes and rename

const vaults = new Map();        // document -> the vault folder its last check reported (for words.txt)

/** A WorkspaceEdit from core edits ({ line, start, end, text }); a line past the end appends. */
function workspaceEdit(doc, edits) {
  const we = new vscode.WorkspaceEdit();
  for (const e of edits) {
    if (e.line >= doc.lineCount) {
      const last = doc.lineCount - 1;
      const end = doc.lineAt(last).text.length;
      we.insert(doc.uri, new vscode.Position(last, end), "\n" + e.text);
    } else {
      we.replace(doc.uri, new vscode.Range(e.line, e.start, e.line, e.end), e.text);
    }
  }
  return we;
}

const codeActionProvider = {
  provideCodeActions(doc, _range, context) {
    const mine = context.diagnostics.filter((d) => d.source === "tabula");
    if (!mine.length) return [];
    const o = core.outline(expandedText(doc));
    const names = [...o.definitions.map((d) => d.term), ...o.components.map((c) => c.name)];
    const sections = o.headings.map((h) => h.title).filter(Boolean);
    const text = doc.getText();
    const actions = [];
    for (const d of mine) {
      const range = { start: d.range.start.character, end: d.range.end.character };
      for (const f of core.quickFixes(text, d.range.start.line, d.message, range, names, sections)) {
        const a = new vscode.CodeAction(f.title, vscode.CodeActionKind.QuickFix);
        a.diagnostics = [d];
        a.isPreferred = !!f.preferred;
        if (f.addWord) a.command = { command: "tabula.addWord", title: f.title, arguments: [doc.uri, f.addWord] };
        else a.edit = workspaceEdit(doc, f.edits);
        actions.push(a);
      }
    }
    return actions;
  },
};

/** Add a word to the vault's words.txt (created if needed), then check the open files again. */
function addWord(uri, word) {
  const root = vaults.get(uri.toString()) || vaultRoot(uri.fsPath);
  const file = path.join(root, "words.txt");
  let text = "";
  try {
    text = fs.readFileSync(file, "utf8");
  } catch {
    text = "# Words the spell check accepts (tabula check --spell), one per line\n";
  }
  const words = new Set(text.split(/\r?\n/).map((l) => l.split("#")[0].trim().toLowerCase()));
  if (!words.has(word.toLowerCase())) {
    if (text && !text.endsWith("\n")) text += "\n";
    fs.writeFileSync(file, text + word + "\n", "utf8");
  }
  vscode.window.setStatusBarMessage(`Tabula: '${word}' added to ${file}`, 4000);
  vscode.workspace.textDocuments.forEach((d) => schedule(d, 0));
}

const renameProvider = {
  prepareRename(doc, pos) {
    const t = core.renameTarget(doc.getText(), pos.line, pos.character);     // throws a message for the user
    return { range: new vscode.Range(pos.line, t.start, pos.line, t.end), placeholder: t.placeholder || t.name };
  },
  provideRenameEdits(doc, pos, newName) {
    return workspaceEdit(doc, core.renameEdits(doc.getText(), pos.line, pos.character, newName));
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
    vscode.languages.registerCompletionItemProvider(sel, completionProvider, "[", "#"),
    vscode.languages.registerHoverProvider(sel, hoverProvider),
    vscode.languages.registerCodeActionsProvider(sel, codeActionProvider, { providedCodeActionKinds: [vscode.CodeActionKind.QuickFix] }),
    vscode.languages.registerRenameProvider(sel, renameProvider),
    vscode.commands.registerCommand("tabula.addWord", addWord),
    vscode.commands.registerCommand("tabula.checkVault", checkVault),
    vscode.commands.registerCommand("tabula.openPreview", openPreview),
    vscode.window.onDidChangeActiveTextEditor((ed) => { if (ed && preview && isGame(ed.document)) previewDocument(ed.document); }),
    vscode.commands.registerCommand("tabula.checkFile", () => {
      const ed = vscode.window.activeTextEditor;
      if (ed) checkDocument(ed.document);
    }),
    vscode.workspace.onDidOpenTextDocument((doc) => schedule(doc, 0)),
    vscode.workspace.onDidSaveTextDocument((doc) => { schedule(doc, 0); schedulePreview(doc, 0); }),
    vscode.workspace.onDidChangeTextDocument((e) => {
      const cfg = settings(e.document.uri);
      if (cfg.run === "onType" && e.contentChanges.length) schedule(e.document, cfg.delay);
      if (e.contentChanges.length) schedulePreview(e.document, cfg.delay);
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
