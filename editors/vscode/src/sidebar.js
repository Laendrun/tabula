"use strict";
// The Tabula panel in the activity bar: the vault's games (with their check status) and the wishlist.
const vscode = require("vscode");
const fs = require("fs");
const os = require("os");
const path = require("path");
const core = require("./core");

const SEVERITY = { error: 0, warning: 1, ok: 2, unknown: 3 };

/** The worst problem among some files' diagnostics: "error", "warning", or "ok". */
function statusOf(files) {
  let worst = "ok";
  for (const f of files) {
    for (const d of vscode.languages.getDiagnostics(vscode.Uri.file(f))) {
      if (d.source !== "tabula") continue;
      if (d.severity === vscode.DiagnosticSeverity.Error) return "error";
      if (d.severity === vscode.DiagnosticSeverity.Warning) worst = "warning";
    }
  }
  return worst;
}

const ICONS = {
  error: ["error", "list.errorForeground"],
  warning: ["warning", "list.warningForeground"],
  ok: ["pass", "testing.iconPassed"],
};

function register(context, deps) {
  const { runTabula, settings, checkVault } = deps;
  let games = null;            // last `tabula list --json`
  let wishes = null;           // last `tabula wish --json`
  let checked = false;

  const cfg = () => settings((vscode.workspace.workspaceFolders || [])[0]?.uri);
  const base = (c) => [...c.extraArgs, ...(c.vault ? ["--vault", c.vault] : [])];

  async function load(args) {
    const c = cfg();
    const r = await runTabula([...base(c), ...args], c, undefined, true).done;
    if (!r || r.code !== 0) return null;
    try {
      return JSON.parse(r.out);
    } catch {
      return null;
    }
  }

  // ---------------------------------------------------------------- games
  const gamesChanged = new vscode.EventEmitter();
  const gamesProvider = {
    onDidChangeTreeData: gamesChanged.event,
    async getChildren(el) {
      if (!el) {
        games = games || (await load(["list", "--json"]));
        if (!games) return [{ kind: "message", label: "No games (or tabula couldn't run: see Output → Tabula)" }];
        if (!checked) {                     // fill in the ✓/⚠ once, quietly
          checked = true;
          checkVault({ quiet: true });
        }
        return games.games.map((g) => ({ kind: "game", game: g }));
      }
      if (el.kind !== "game") return [];
      const g = el.game;
      return [
        ...Object.entries(g.translations).map(([lang, file]) => ({ kind: "file", label: `${g.title} (${lang})`, file, icon: "globe" })),
        ...g.sheets.map((file) => ({ kind: "sheet", label: path.basename(file), file, game: g })),
      ];
    },
    getTreeItem(el) {
      if (el.kind === "message") return new vscode.TreeItem(el.label);
      if (el.kind === "game") {
        const g = el.game;
        const hasKids = g.sheets.length || Object.keys(g.translations).length;
        const item = new vscode.TreeItem(g.title, hasKids ? vscode.TreeItemCollapsibleState.Collapsed : vscode.TreeItemCollapsibleState.None);
        const players = g.players ? `${g.players}${g.players_note ? ` (${g.players_note})` : ""}` : "";
        item.description = [players && `${players} players`, g.duration && `${g.duration} min`].filter(Boolean).join(" · ");
        item.tooltip = [g.title, item.description, g.location && `📦 ${g.location}`].filter(Boolean).join("\n");
        const status = statusOf([g.path, ...Object.values(g.translations), ...g.sheets]);
        const [icon, color] = ICONS[status];
        item.iconPath = new vscode.ThemeIcon(icon, new vscode.ThemeColor(color));
        item.contextValue = g.sheets.length ? "game-with-sheet" : "game";
        item.resourceUri = vscode.Uri.file(g.path);
        item.command = { command: "vscode.open", title: "Open", arguments: [vscode.Uri.file(g.path)] };
        return item;
      }
      const item = new vscode.TreeItem(el.label);
      item.iconPath = new vscode.ThemeIcon(el.kind === "sheet" ? "table" : el.icon || "file");
      item.contextValue = el.kind;
      item.command = { command: "vscode.open", title: "Open", arguments: [vscode.Uri.file(el.file)] };
      return item;
    },
  };

  // ---------------------------------------------------------------- wishlist
  const wishesChanged = new vscode.EventEmitter();
  const wishProvider = {
    onDidChangeTreeData: wishesChanged.event,
    async getChildren(el) {
      if (el) return [];
      wishes = wishes || (await load(["wish", "--json"]));
      if (!wishes) return [];
      return wishes.map((w) => ({ kind: "wish", wish: w }));
    },
    getTreeItem(el) {
      const w = el.wish;
      const item = new vscode.TreeItem(String(w.name));
      const game = w.for && games ? (games.games.find((g) => g.slug === w.for) || {}).title || w.for : w.for;
      item.description = [game && `for ${game}`, w.price].filter(Boolean).join(" · ");
      item.tooltip = [w.name, item.description, w.note, w.link].filter(Boolean).join("\n");
      item.iconPath = new vscode.ThemeIcon(w.priority === 1 ? "star-full" : w.priority === 2 ? "star-half" : "star-empty");
      item.contextValue = "wish";
      const file = games ? path.join(games.vault, "wishlist.yaml") : null;
      if (file) item.command = { command: "tabula.openWish", title: "Open", arguments: [file, String(w.name)] };
      return item;
    },
  };

  function refresh() {
    games = null;
    wishes = null;
    gamesChanged.fire();
    wishesChanged.fire();
  }

  // ---------------------------------------------------------------- commands
  async function buildSite() {
    const c = cfg();
    if (!games) games = await load(["list", "--json"]);
    if (!games) return;
    const folder = c.siteFolder ? path.resolve(games.vault, c.siteFolder) : path.join(games.vault, "site");
    const r = await vscode.window.withProgress({ location: vscode.ProgressLocation.Notification, title: "Tabula: writing the site…" },
      () => runTabula([...base(c), "site", "-o", folder], c, undefined, true).done);
    if (!r) return;
    if (r.code !== 0) return vscode.window.showErrorMessage(`Tabula: ${(r.err || r.out).trim().split("\n").pop()}`);
    const pick = await vscode.window.showInformationMessage(`Tabula: site written to ${folder}`, "Open in browser");
    if (pick) vscode.env.openExternal(vscode.Uri.file(path.join(folder, "index.html")));
  }

  async function buildBook() {
    const c = cfg();
    if (!games) games = await load(["list", "--json"]);
    if (!games) return;
    const dest = await vscode.window.showSaveDialog({
      defaultUri: vscode.Uri.file(path.join(games.vault, `${core.slug(games.name)}.epub`)), filters: { "EPUB book": ["epub"] },
    });
    if (!dest) return;
    const r = await vscode.window.withProgress({ location: vscode.ProgressLocation.Notification, title: "Tabula: writing the book…" },
      () => runTabula([...base(c), "book", "-o", dest.fsPath], c, undefined, true).done);
    if (!r) return;
    if (r.code !== 0) return vscode.window.showErrorMessage(`Tabula: ${(r.err || r.out).trim().split("\n").pop()}`);
    const pick = await vscode.window.showInformationMessage(`Tabula: book written to ${dest.fsPath}`, "Show in folder");
    if (pick) vscode.commands.executeCommand("revealFileInOS", dest);
  }

  async function printSheet(el) {
    const g = el && (el.game || (el.kind === "game" && el.game));
    if (!g || !g.sheets.length) return;
    let sheet = el.kind === "sheet" ? el.file : g.sheets[0];
    if (el.kind !== "sheet" && g.sheets.length > 1) {
      const pick = await vscode.window.showQuickPick(g.sheets.map((f) => path.basename(f)), { placeHolder: "Which score sheet?" });
      if (!pick) return;
      sheet = g.sheets.find((f) => path.basename(f) === pick);
    }
    const counts = core.playerCounts(g.players);
    let players = null;
    if (counts.length > 1) {
      const pick = await vscode.window.showQuickPick([`${counts[counts.length - 1]} (the most)`, ...counts.slice(0, -1).reverse().map(String)],
        { placeHolder: "How many players (columns)?" });
      if (!pick) return;
      players = parseInt(pick, 10);
    }
    const c = cfg();
    const out = path.join(os.tmpdir(), `tabula-${g.slug}-${path.basename(sheet, ".sheet")}-${players || "all"}.html`);
    const r = await runTabula([...base(c), "sheet", sheet, ...(players ? ["-p", String(players)] : []), "-o", out], c, undefined, true).done;
    if (!r) return;
    if (r.code !== 0) return vscode.window.showErrorMessage(`Tabula: ${(r.err || r.out).trim().split("\n").pop()}`);
    vscode.env.openExternal(vscode.Uri.file(out));              // print it from the browser
  }

  async function addWish() {
    if (!games) games = await load(["list", "--json"]);
    const name = await vscode.window.showInputBox({ prompt: "Game or extension you'd like", placeHolder: "Cascadia" });
    if (!name) return;
    const choices = [{ label: "A new game", slug: null }, ...(games ? games.games : []).map((g) => ({ label: `An extension of ${g.title}`, slug: g.slug }))];
    const kind = await vscode.window.showQuickPick(choices, { placeHolder: "A new game, or an extension of one you have?" });
    if (!kind) return;
    const prio = await vscode.window.showQuickPick(["1 (most wanted)", "2", "3", "no priority"], { placeHolder: "Priority" });
    if (!prio) return;
    const price = await vscode.window.showInputBox({ prompt: "Price (optional)", placeHolder: "35 CHF" });
    const args = ["wish", "add", name, ...(kind.slug ? ["--for", kind.slug] : []),
                  ...(/^\d/.test(prio) ? ["--priority", prio[0]] : []), ...(price ? ["--price", price] : [])];
    const c = cfg();
    const r = await runTabula([...base(c), ...args], c, undefined, true).done;
    if (r && r.code !== 0) return vscode.window.showErrorMessage(`Tabula: ${(r.err || r.out).trim().split("\n").pop()}`);
    wishes = null;
    wishesChanged.fire();
  }

  async function openWish(file, name) {
    const doc = await vscode.workspace.openTextDocument(vscode.Uri.file(file));
    const ed = await vscode.window.showTextDocument(doc);
    const lines = doc.getText().split(/\r?\n/);
    const k = lines.findIndex((l) => l.replace(/["']/g, "").match(new RegExp(`^- name:\\s*${name.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")}\\s*$`)));
    if (k >= 0) {
      const pos = new vscode.Position(k, 0);
      ed.selection = new vscode.Selection(pos, pos);
      ed.revealRange(new vscode.Range(pos, pos), vscode.TextEditorRevealType.InCenter);
    }
  }

  context.subscriptions.push(
    vscode.window.registerTreeDataProvider("tabula.games", gamesProvider),
    vscode.window.registerTreeDataProvider("tabula.wishlist", wishProvider),
    vscode.commands.registerCommand("tabula.refreshPanel", refresh),
    vscode.commands.registerCommand("tabula.buildSite", buildSite),
    vscode.commands.registerCommand("tabula.buildBook", buildBook),
    vscode.commands.registerCommand("tabula.printSheet", printSheet),
    vscode.commands.registerCommand("tabula.addWish", addWish),
    vscode.commands.registerCommand("tabula.openWish", openWish),
    vscode.commands.registerCommand("tabula.previewGame", async (el) => {
      if (!el || !el.game) return;
      await vscode.window.showTextDocument(vscode.Uri.file(el.game.path));
      vscode.commands.executeCommand("tabula.openPreview");
    }),
    vscode.languages.onDidChangeDiagnostics(() => gamesChanged.fire()),       // ✓/⚠ follow the checks
    vscode.workspace.onDidSaveTextDocument((doc) => {
      const name = path.basename(doc.uri.fsPath);
      if (/\.(game|sheet)$/.test(name) || name === "vault.yaml") {
        games = null;
        gamesChanged.fire();
      }
      if (name === "wishlist.yaml") {
        wishes = null;
        wishesChanged.fire();
      }
    })
  );
  return { gamesProvider, wishProvider, refresh };
}

module.exports = { register, statusOf };
