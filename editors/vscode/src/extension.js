// Tabula for VS Code: runs `tabula check` while you write and shows the results as squiggles.
"use strict";

const vscode = require("vscode");
const cp = require("child_process");
const fs = require("fs");
const os = require("os");
const path = require("path");
const core = require("./core");
const sidebar = require("./sidebar");

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
  for (const [f, list] of byFile) {
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

// ------------------------------------------------------------------ the outline: tabula reads the file

// The extension doesn't parse .game files: `tabula outline --json` does, with the same parser as every other
// tabula command. Its result is kept for each version of a document.
const outlines = new Map();          // document uri -> { version, promise }
const fileOutlines = new Map();      // other files (fragments) -> { mtime, promise }

function outlineRun(file, cfg, text) {
  const args = core.outlineArgs({ file, vault: cfg.vault, extraArgs: cfg.extraArgs, stdin: text !== undefined });
  return runTabula(args, cfg, text, true).done.then((r) => {
    if (!r) return null;
    if (r.code !== 0) {
      output.appendLine(`$ tabula outline ${file}\n${(r.err || r.out).trim()}`);
      return null;
    }
    try {
      return core.parseOutline(r.out);
    } catch (e) {
      output.appendLine(`tabula outline ${file}: ${e.message}`);
      return null;
    }
  });
}

/** The outline of a document as it is now (unsaved changes included): a promise, null when tabula fails. */
function outlineOf(doc) {
  const key = doc.uri.toString();
  const version = doc.version !== undefined ? doc.version : doc.getText();
  const c = outlines.get(key);
  if (c && c.version === version) return c.promise;
  const promise = outlineRun(doc.uri.fsPath, settings(doc.uri), doc.getText());
  outlines.set(key, { version, promise });
  return promise;
}

/** The outline of a file on disk (a shared fragment), kept until the file changes. */
function outlineOfFile(file, cfg) {
  let mtime = 0;
  try {
    mtime = fs.statSync(file).mtimeMs;
  } catch {
    return Promise.resolve(null);
  }
  const c = fileOutlines.get(file);
  if (c && c.mtime === mtime) return c.promise;
  const promise = outlineRun(file, cfg);
  fileOutlines.set(file, { mtime, promise });
  return promise;
}

const lineText = (doc, line) => (line < doc.lineCount ? doc.lineAt(line).text : "");
/** A VS Code range from the outline's columns (characters) on a line. */
const rangeOf = (doc, line, a, b) => {
  const t = lineText(doc, line);
  return new vscode.Range(line, core.u16(t, a), line, core.u16(t, b));
};
/** The cursor's column as the outline counts it. */
const colOf = (doc, pos) => core.cp(lineText(doc, pos.line), pos.character);

// ------------------------------------------------------------------ outline view, folding, go to definition

const symbols = {
  async provideDocumentSymbols(doc) {
    const o = await outlineOf(doc);
    if (!o) return [];
    const root = [];
    const stack = [];
    const range = (a, b) => new vscode.Range(a, 0, b, lineText(doc, Math.min(b, doc.lineCount - 1)).length);
    for (const h of o.headings) {
      const s = new vscode.DocumentSymbol(
        (h.key ? "★ " : "") + (h.title || "(untitled)"),
        [h.cond, ...h.roles.map((r) => "#" + r)].filter(Boolean).length ? `{${[h.cond, ...h.roles.map((r) => "#" + r)].filter(Boolean).join(" ")}}` : "",
        vscode.SymbolKind.Namespace, range(h.line, h.end), range(h.line, h.line)
      );
      while (stack.length && stack[stack.length - 1].level >= h.level) stack.pop();
      (stack.length ? stack[stack.length - 1].sym.children : root).push(s);
      stack.push({ level: h.level, sym: s });
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
  async provideFoldingRanges(doc) {
    const o = await outlineOf(doc);
    if (!o) return [];
    return [...o.headings, ...o.definitions]
      .filter((x) => x.end > x.line)
      .map((x) => new vscode.FoldingRange(x.line, x.end));
  },
};

const definitionProvider = {
  async provideDefinition(doc, pos) {
    const o = await outlineOf(doc);
    if (!o) return null;
    const inc = core.includeUnder(o, pos.line);
    if (inc && inc.file) return new vscode.Location(vscode.Uri.file(inc.file), new vscode.Position(inc.section_line || 0, 0));
    const ref = core.refUnder(o, pos.line, colOf(doc, pos));
    if (!ref) return null;
    const found = core.targets(o, ref);
    if (!found.length) return null;
    return found.map((t) => new vscode.Location(t.file ? vscode.Uri.file(t.file) : doc.uri, new vscode.Position(t.line, 0)));
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
  const m = path.basename(file).match(/^.*\.([a-z]{2,3}(?:-[A-Za-z0-9]{2,8})?)\.game$/);
  return m ? m[1] : null;
}

/** _shared/<name>.<lang>.game when the document is a translation and it exists, else _shared/<name>.game. */
function fragmentFile(docFile, name) {
  if (!/^[^/\\:]+$/.test(name) || name.startsWith(".")) return null;
  const dir = path.join(vaultRoot(docFile), "_shared");
  const lang = fileLang(docFile);
  const cands = (lang ? [path.join(dir, `${name}.${lang}.game`)] : []).concat(path.join(dir, `${name}.game`));
  return cands.find((f) => fs.existsSync(f)) || null;
}

function fragmentNames(docFile) {
  try {
    return fs.readdirSync(path.join(vaultRoot(docFile), "_shared"))
      .filter((f) => f.endsWith(".game") && !/\.[a-z]{2,3}(?:-[A-Za-z0-9]{2,8})?\.game$/.test(f))
      .map((f) => f.slice(0, -5)).sort();
  } catch {
    return [];
  }
}

async function includeCompletions(doc, pos, ctx) {
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
  const o = file && (await outlineOfFile(file, settings(doc.uri)));
  if (!o) return undefined;
  return core.sectionItems(o.headings).map((x, i) => {
    const item = new vscode.CompletionItem({ label: x.label, description: x.detail }, KINDS[x.kind]);
    Object.assign(item, { range, insertText: x.label + end, filterText: x.label, sortText: String(i).padStart(5, "0"),
                          detail: `${x.kind} in ${ctx.name}` });
    return item;
  });
}

function symbolMarkdown(s) {
  const pic = s.image ? `![${s.name}](${vscode.Uri.file(s.image).toString()}|height=32)` : s.text;
  return `${pic}  \`:${s.name}:\`${s.image && s.text ? ` — ${s.text} in the terminal` : ""}\n\nfrom ${s.from}`;
}

// the JSON Schemas of spec/schemas (copied into the extension): frontmatter keys and their descriptions
const SCHEMAS = {};
for (const name of ["game", "sheet"]) {
  try {
    SCHEMAS[name] = JSON.parse(fs.readFileSync(path.join(__dirname, "..", "schemas", `${name}.schema.json`), "utf8"));
  } catch {
    SCHEMAS[name] = null;
  }
}
const kindOf = (doc) => (doc.uri.fsPath.endsWith(".sheet") ? "sheet" : "game");

function frontmatterCompletions(doc, pos, o) {
  const fm = core.frontmatterContext(o, lineText(doc, pos.line), pos.line, pos.character);
  if (!fm) return null;
  const range = new vscode.Range(pos.line, fm.start, pos.line, pos.character);
  return core.schemaKeys(SCHEMAS, kindOf(doc), fm.level).filter((k) => !fm.present.includes(k.key)).map((k) => {
    const item = new vscode.CompletionItem(k.key, vscode.CompletionItemKind.Property);
    item.range = range;
    item.insertText = k.key + ": ";
    item.detail = fm.level === "option" ? "extension/variant detail" : kindOf(doc) === "sheet" ? "sheet setting" : "frontmatter";
    item.documentation = new vscode.MarkdownString(k.description);
    return item;
  });
}

const completionProvider = {
  async provideCompletionItems(doc, pos) {
    const text = lineText(doc, pos.line);
    const inc = core.includeContext(text, pos.character);
    if (inc) return includeCompletions(doc, pos, inc);
    const o = await outlineOf(doc);
    if (!o) return undefined;
    const fmItems = frontmatterCompletions(doc, pos, o);
    if (fmItems) return fmItems;
    const sctx = core.symbolContext(text, pos.character);
    if (sctx) {
      if (!o.symbols.length) return undefined;
      const range = new vscode.Range(pos.line, sctx.start, pos.line, pos.character + (sctx.closed ? 1 : 0));
      return o.symbols.map((s) => {
        const item = new vscode.CompletionItem({ label: `:${s.name}:`, description: s.text || s.src }, vscode.CompletionItemKind.EnumMember);
        item.range = range;
        item.insertText = `:${s.name}:`;
        item.filterText = `:${s.name}`;
        item.detail = `symbol from ${s.from}`;
        item.documentation = new vscode.MarkdownString(symbolMarkdown(s));
        return item;
      });
    }
    const vctx = core.valueContext(text, pos.character);
    if (vctx) {
      const range = new vscode.Range(pos.line, vctx.start, pos.line, pos.character);
      return o.values.map((v) => {
        const item = new vscode.CompletionItem({ label: v.name, description: v.value }, vscode.CompletionItemKind.Constant);
        item.range = range;
        item.insertText = v.name + (vctx.closed ? "" : "}");
        item.detail = `value from ${v.from}`;
        return item;
      });
    }
    const ctx = core.completionContext(text, pos.character);
    if (!ctx) return undefined;
    const all = core.completionsFor(o);
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
  async provideHover(doc, pos) {
    const o = await outlineOf(doc);
    if (!o) return null;
    const col = colOf(doc, pos);
    const md = (text, line, a, b) => new vscode.Hover(new vscode.MarkdownString(text), rangeOf(doc, line, a, b));
    const fk = core.frontmatterKeyAt(o, pos.line, col);
    if (fk) return md(core.frontmatterHover(SCHEMAS, kindOf(doc), fk.level, fk.key), pos.line, fk.start, fk.end);
    const inc = core.includeUnder(o, pos.line);
    if (inc) return md(core.includeHover(inc), pos.line, inc.start, inc.end);
    const text = lineText(doc, pos.line);
    const sym = core.symbolAt(text, pos.character);
    const known = sym && o.symbols.find((s) => s.name === sym.name);
    if (known) {
      return new vscode.Hover(new vscode.MarkdownString(symbolMarkdown(known)), new vscode.Range(pos.line, sym.start, pos.line, sym.end));
    }
    const link = core.linkAt(o, pos.line, col);
    if (link && link.kind === "image") {
      const body = link.path && link.exists ? `![](${vscode.Uri.file(link.path).toString()}|height=220)\n\n\`${link.src}\``
        : link.url ? `![](${link.url}|height=220)`
        : link.outside ? `\`${link.src}\` is outside the vault: tabula doesn't use it` : `Image not found: \`${link.src}\``;
      return md(body, pos.line, link.start, link.end);
    }
    const val = core.valueAt(text, pos.character);
    if (val) {
      const v = o.values.find((x) => x.name === val.name);
      const body = v ? `**${v.name}** = \`${v.value}\`\n\nfrom ${v.from}`
        : `No value \`${val.name}\`: define it under \`values:\` in the frontmatter or in vault.yaml`;
      return new vscode.Hover(new vscode.MarkdownString(body), new vscode.Range(pos.line, val.start, pos.line, val.end));
    }
    const ref = core.refUnder(o, pos.line, col);
    if (!ref) return null;
    const body = core.hoverFor(o, ref, (p) => vscode.Uri.file(p).toString());
    return body ? md(body, pos.line, ref.start, ref.end) : null;
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

// ------------------------------------------------------------------ references, use counts, links, inline hints

const loc = (doc, r) => new vscode.Location(doc.uri, rangeOf(doc, r.line, r.start, r.end));

const referenceProvider = {
  async provideReferences(doc, pos, context) {
    const o = await outlineOf(doc);
    const found = o && core.occurrencesAt(o, pos.line, colOf(doc, pos));
    if (!found) return [];
    return [...(context && context.includeDeclaration === false ? [] : found.definitions), ...found.references].map((r) => loc(doc, r));
  },
};

const codeLensProvider = {
  async provideCodeLenses(doc) {
    const o = await outlineOf(doc);
    if (!o) return [];
    const byKey = new Map();
    for (const r of o.references) {
      const k = (r.section ? "#" : "") + r.fold;
      if (!byKey.has(k)) byKey.set(k, []);
      byKey.get(k).push(r);
    }
    return core.useCounts(o).map((u) => {
      const where = byKey.get((u.kind === "section" ? "#" : "") + u.fold) || [];
      const range = new vscode.Range(u.line, 0, u.line, 0);
      const title = u.count === 0 ? "not used" : u.count === 1 ? "used once" : `used ${u.count} times`;
      return new vscode.CodeLens(range, u.count
        ? { title, command: "editor.action.showReferences", arguments: [doc.uri, new vscode.Position(u.line, 0), where.map((r) => loc(doc, r))] }
        : { title, command: "" });
    });
  },
};

const linkProvider = {
  async provideDocumentLinks(doc) {
    const o = await outlineOf(doc);
    if (!o) return [];
    return o.links.filter((l) => (l.file || l.path) && l.exists).map((l) => {
      const link = new vscode.DocumentLink(rangeOf(doc, l.line, l.start, l.end), vscode.Uri.file(l.file || l.path));
      link.tooltip = l.kind === "fragment" ? "Open the shared fragment" : "Open the image";
      return link;
    });
  },
};

const inlayHintsProvider = {
  async provideInlayHints(doc, range) {
    const o = await outlineOf(doc);
    if (!o) return [];
    return o.hints
      .filter((h) => h.line >= range.start.line && h.line <= range.end.line)
      .map((h) => {
        const hint = new vscode.InlayHint(new vscode.Position(h.line, core.u16(lineText(doc, h.line), h.character)), h.label);
        hint.paddingLeft = true;
        hint.tooltip = h.tooltip;
        return hint;
      });
  },
};

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
  const o = (await outlineOf(doc)) || { definitions: [] };
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
  async provideCodeActions(doc, _range, context) {
    const mine = context.diagnostics.filter((d) => d.source === "tabula");
    if (!mine.length) return [];
    const o = await outlineOf(doc);
    if (!o) return [];
    const names = [...core.allDefinitions(o).map((d) => d.term), ...core.allComponents(o).map((c) => c.name)];
    const sections = o.headings.map((h) => h.title).filter(Boolean);
    const text = doc.getText();
    const actions = [];
    for (const d of mine) {
      const range = { start: d.range.start.character, end: d.range.end.character };
      for (const f of core.quickFixes(text, d.range.start.line, d.message, range, names, sections, o.glossary_line)) {
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
  async prepareRename(doc, pos) {
    const o = await outlineOf(doc);
    if (!o) throw new Error("tabula couldn't read this file (see Output → Tabula)");
    const t = core.renameTarget(o, pos.line, colOf(doc, pos));     // throws a message for the user
    return { range: rangeOf(doc, pos.line, t.start, t.end), placeholder: t.placeholder || t.name };
  },
  async provideRenameEdits(doc, pos, newName) {
    const o = await outlineOf(doc);
    if (!o) throw new Error("tabula couldn't read this file (see Output → Tabula)");
    const edits = core.renameEdits(o, pos.line, colOf(doc, pos), newName).map((e) => {
      const t = lineText(doc, e.line);
      return { ...e, start: core.u16(t, e.start), end: core.u16(t, e.end) };
    });
    return workspaceEdit(doc, edits);
  },
};

// ------------------------------------------------------------------ formatting (tabula fmt)

const formatter = {
  async provideDocumentFormattingEdits(doc) {
    const cfg = settings(doc.uri);
    const { done } = runTabula(core.fmtArgs({ file: doc.uri.fsPath, vault: cfg.vault, extraArgs: cfg.extraArgs }),
                               cfg, doc.getText(), true);
    const r = await done;
    if (!r) return [];
    if (r.code !== 0) {
      const why = (r.err || r.out).trim();
      output.appendLine(`$ tabula fmt ${doc.uri.fsPath} --stdin\n${why}`);
      vscode.window.setStatusBarMessage(`Tabula: ${why.split("\n").pop() || "not formatted"} (see Output → Tabula)`, 6000);
      return [];
    }
    r.out = r.out.replace(/\r+\n/g, "\n");         // VS Code writes the document's own line endings
    const text = doc.getText();
    if (r.out === text || r.out.replace(/\r\n/g, "\n") === text.replace(/\r\n/g, "\n")) return [];
    const last = doc.lineAt(doc.lineCount - 1);
    return [vscode.TextEdit.replace(new vscode.Range(0, 0, doc.lineCount - 1, last.text.length), r.out)];
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
  diagnostics = vscode.languages.createDiagnosticCollection("tabula");
  output = vscode.window.createOutputChannel("Tabula");
  const sel = { language: "tabula", scheme: "file" };
  context.subscriptions.push(
    diagnostics,
    output,
    vscode.languages.registerDocumentSymbolProvider(sel, symbols),
    vscode.languages.registerFoldingRangeProvider(sel, folding),
    vscode.languages.registerDefinitionProvider(sel, definitionProvider),
    vscode.languages.registerCompletionItemProvider(sel, completionProvider, "[", "#", "="),
    vscode.languages.registerHoverProvider(sel, hoverProvider),
    vscode.languages.registerCodeActionsProvider(sel, codeActionProvider, { providedCodeActionKinds: [vscode.CodeActionKind.QuickFix] }),
    vscode.languages.registerRenameProvider(sel, renameProvider),
    vscode.languages.registerReferenceProvider(sel, referenceProvider),
    vscode.languages.registerCodeLensProvider(sel, codeLensProvider),
    vscode.languages.registerDocumentLinkProvider(sel, linkProvider),
    vscode.languages.registerInlayHintsProvider(sel, inlayHintsProvider),
    ...(vscode.languages.registerDocumentDropEditProvider
      ? [vscode.languages.registerDocumentDropEditProvider(sel, dropProvider)] : []),
    ...(vscode.languages.registerDocumentPasteEditProvider
      ? [vscode.languages.registerDocumentPasteEditProvider(sel, pasteProvider, {
          providedPasteEditKinds: vscode.DocumentDropOrPasteEditKind ? [vscode.DocumentDropOrPasteEditKind.Empty.append("tabula", "image")] : [],
          pasteMimeTypes: ["image/png", "image/jpeg", "image/gif", "image/webp", "text/uri-list"],
        })] : []),
    vscode.commands.registerCommand("tabula.addWord", addWord),
    vscode.languages.registerDocumentFormattingEditProvider(sel, formatter),
    vscode.commands.registerCommand("tabula.formatFile", () => vscode.commands.executeCommand("editor.action.formatDocument")),
    vscode.commands.registerCommand("tabula.formatVault", formatVault),
    vscode.commands.registerCommand("tabula.checkVault", () => checkVault()),
    vscode.commands.registerCommand("tabula.openPreview", openPreview),
    vscode.window.onDidChangeActiveTextEditor((ed) => { if (ed && preview && isGame(ed.document)) previewDocument(ed.document); }),
    vscode.window.onDidChangeTextEditorSelection((e) => {          // the preview follows the cursor
      if (!preview || e.textEditor.document !== preview.doc || !settings(preview.doc.uri).followCursor) return;
      clearTimeout(preview.cursorTimer);
      const line = e.selections[0].active.line + 1;
      preview.cursorTimer = setTimeout(() => preview && preview.panel.webview.postMessage({ line }), 120);
    }),
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
      outlines.delete(key);
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
  sidebar.register(context, { runTabula, settings, checkVault });
}

function deactivate() {
  for (const t of timers.values()) clearTimeout(t);
  for (const c of running.values()) if (c && c.exitCode === null) c.kill();
}

module.exports = { activate, deactivate };
