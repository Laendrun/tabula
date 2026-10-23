// Pure helpers for the Tabula extension: no `vscode` import, so they can be tested with plain node.
//
// The extension doesn't parse .game files: the language server (`tabula lsp`) does, with the same parser as
// every tabula command. What is left here builds tabula's command lines and reads its outputs (check, the
// preview), places pasted images, and sorts the Tabula panel.
"use strict";

/** Command-line arguments for `tabula check` (file = the file being edited, or none for the whole vault). */
function checkArgs({ file, vault, extraArgs = [], definitions = false, stdin = false, spell = false }) {
  const args = [...extraArgs];
  if (vault) args.push("--vault", vault);
  args.push("check");
  if (file) args.push(file);
  args.push("--json");
  if (stdin) args.push("--stdin");
  if (definitions) args.push("--definitions");
  if (spell) args.push("--spell");
  return args;
}

/** Arguments for the preview: `tabula sheet` for a score sheet, else `tabula export --interactive`. */
function previewArgs({ file, vault, extraArgs = [] }) {
  const args = [...extraArgs];
  if (vault) args.push("--vault", vault);
  if (/\.sheet$/i.test(file)) args.push("sheet", file, "--stdin", "-o", "-");
  else args.push("export", file, "--interactive", "--lines", "--stdin", "-o", "-");
  return args;
}

/** Arguments for `tabula fmt`: one file from stdin (to stdout), or the whole vault. */
function fmtArgs({ file, vault, extraArgs = [] }) {
  const args = [...extraArgs];
  if (vault) args.push("--vault", vault);
  args.push("fmt");
  if (file) args.push(file, "--stdin");
  return args;
}

/** Replace ${workspaceFolder} (and ~ at the start) in a setting. */
function expand(value, workspaceFolder, home) {
  if (typeof value !== "string") return value;
  let v = value.split("${workspaceFolder}").join(workspaceFolder || "");
  if (home && (v === "~" || v.startsWith("~/") || v.startsWith("~\\"))) v = home + v.slice(1);
  return v;
}

/** Parse `tabula check --json`. Throws with a readable message when the output isn't the JSON we expect. */
function parseCheckOutput(stdout) {
  const start = stdout.indexOf("{");
  if (start < 0) throw new Error("tabula printed no JSON (is it version 0.7 or newer?)");
  const data = JSON.parse(stdout.slice(start));
  if (!Array.isArray(data.issues)) throw new Error("unexpected output from tabula check --json");
  return { vault: data.vault || "", files: data.files || [], issues: data.issues };
}

/**
 * Where to put the squiggle on a line: the first thing the message quotes that appears on that line
 * ([[ref]], {condition}, 'text', "text"), otherwise the whole line without its indentation.
 * Returns [startColumn, endColumn] (0-based, end exclusive).
 */
function issueColumns(lineText, message) {
  const candidates = [];
  const patterns = [/^unknown word '(.+?)'(?= \(|$)/g, /\[\[[^\]]*\]\]?/g, /\{[^{}]*\}/g, /'([^']+)'/g, /"([^"]+)"/g, /‘([^’]+)’/g];
  for (const re of patterns) {
    for (const m of message.matchAll(re)) candidates.push(m[1] !== undefined ? m[1] : m[0]);
  }
  for (const c of candidates) {
    if (!c.trim()) continue;
    if (/^[\p{L}']+$/u.test(c)) {     // a word ("unknown word 'carte'"): the whole word, not part of "cartes"
      const esc = c.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
      const w = new RegExp(`(?<![\\p{L}\\p{N}_'])${esc}(?![\\p{L}\\p{N}_])`, "u").exec(lineText);
      if (w) return [w.index, w.index + c.length];
    }
    let at = lineText.indexOf(c);
    if (at < 0) at = lineText.toLowerCase().indexOf(c.toLowerCase());
    if (at >= 0) return [at, at + c.length];
  }
  const first = lineText.search(/\S/);
  return first < 0 ? [0, lineText.length] : [first, lineText.trimEnd().length];
}

/** VS Code severity for a tabula issue level: TODO reminders and unknown words are information, not warnings. */
function severity(level, S) {
  return level === "error" ? S.Error : level === "todo" || level === "spelling" ? S.Information : S.Warning;
}

/** Search key used by tabula for references: case, accents and plurals ignored. */
function fold(text) {
  const plain = text.normalize("NFKD").replace(/[̀-ͯ]/g, "").toLowerCase();
  return plain
    .replace(/[^\p{L}\p{N}_\s'-]/gu, " ")
    .split(/\s+/)
    .filter(Boolean)
    .map((w) => (w.length > 2 && /[sx]$/.test(w) && !w.endsWith("ss") ? w.slice(0, -1) : w))
    .join(" ");
}

// ------------------------------------------------------------------ preview

/**
 * The exported page, made ready for a VS Code webview: a content security policy that only lets the page's
 * own scripts run (with a nonce), a bridge to the extension (links, remembered scroll position).
 */
function previewHtml(html, nonce, cspSource) {
  const csp = `default-src 'none'; img-src data: https: ${cspSource}; style-src 'unsafe-inline' https://fonts.googleapis.com; ` +
    `font-src https://fonts.gstatic.com; script-src 'nonce-${nonce}';`;
  const bridge = `<script nonce="${nonce}">
(function () {
  var api = acquireVsCodeApi();
  window.tabulaVscode = api;
  function save(k, v) { var s = api.getState() || {}; s[k] = v; api.setState(s); }
  window.addEventListener('load', function () {
    var s = api.getState() || {};
    if (s.scroll) window.scrollTo(0, s.scroll);
  });
  var t = null;
  window.addEventListener('scroll', function () {
    clearTimeout(t);
    t = setTimeout(function () { save('scroll', window.scrollY); }, 100);
  });
  // the editor's cursor: scroll to the block it is in (the last one starting at or before its line)
  function toLine(line) {
    var best = null, at = -1;
    var els = document.querySelectorAll('[data-line]');
    for (var i = 0; i < els.length; i++) {
      var l = +els[i].getAttribute('data-line');
      if (l <= line && l >= at && els[i].getClientRects().length) { best = els[i]; at = l; }
    }
    if (!best) return;
    var r = best.getBoundingClientRect();
    if (r.top > 60 && r.bottom < window.innerHeight - 60) return;      // already in view
    window.scrollTo({ top: window.scrollY + r.top - window.innerHeight * 0.25, behavior: 'smooth' });
  }
  window.addEventListener('message', function (e) {
    if (e.data && typeof e.data.line === 'number') toLine(e.data.line);
  });
  // double-click in the preview: put the editor's cursor there
  document.addEventListener('dblclick', function (e) {
    var el = e.target.closest && e.target.closest('[data-line]');
    if (el) api.postMessage({ line: +el.getAttribute('data-line') });
  });
  document.addEventListener('click', function (e) {
    var a = e.target.closest && e.target.closest('a[href]');
    if (!a) return;
    var href = a.getAttribute('href');
    if (href.charAt(0) === '#') return;                 // a term or a section on this page
    e.preventDefault();
    api.postMessage({ open: href });
  });
})();
</script>`;
  return html
    .replace(/<head>/, `<head>\n<meta http-equiv="Content-Security-Policy" content="${csp}">\n${bridge}`)
    .replace(/<script>/g, `<script nonce="${nonce}">`);
}

/** Where a link clicked in the preview goes: {url} for the web, {game: slug} for another game, else null. */
function previewLink(href) {
  if (/^https?:\/\//.test(href)) return { url: href };
  const m = href.match(/^(?:\.\.\/)?([a-z0-9]+(?:-[a-z0-9]+)*)(?:\/index)?\.html(?:#.*)?$/);
  return m ? { game: m[1] } : null;
}

// ------------------------------------------------------------------ pasted images, the Tabula panel

/**
 * Where a pasted or dropped image goes: on a card (inside a definition), as its image:: field (replacing an
 * older one); elsewhere, as ![caption](path) at the cursor. `lines`: the document's lines.
 */
function imagePlacement(o, lines, line, rel, caption = "") {
  const d = o.definitions.find((x) => x.line <= line && line <= x.end);
  if (!d) return { kind: "inline", text: `![${caption}](${rel})` };
  const pic = d.fields.find((f) => f.key === "image");
  if (pic) {                                                   // already has a picture: replace its path
    const m = (lines[pic.line] || "").match(/^(\s*(?::\s*)?image::\s*)(\S*)/);
    if (m) return { kind: "card", term: d.term, edits: [{ line: pic.line, start: m[1].length, end: m[1].length + m[2].length, text: rel }] };
  }
  const first = lines[d.line + 1] || "";
  const rest = first.replace(/^:\s?/, "");
  if (!rest.trim()) return { kind: "card", term: d.term, edits: [{ line: d.line + 1, start: 0, end: first.length, text: `: image:: ${rel}` }] };
  if (d.fields.length) return { kind: "card", term: d.term, edits: [{ line: d.line + 2, start: 0, end: 0, text: `  image:: ${rel}\n` }] };
  // text right after ":": the picture becomes the first field, the text moves to the next line
  return { kind: "card", term: d.term, edits: [{ line: d.line + 1, start: 0, end: first.length, text: `: image:: ${rel}\n  ${rest}` }] };
}

/** "Grande marée" -> "grande-maree" (for file names). */
function slug(text) {
  return text.normalize("NFKD").replace(/[̀-ͯ]/g, "").toLowerCase()
    .replace(/[^a-z0-9]+/g, "-").replace(/^-+|-+$/g, "") || "image";
}

/** A file name for the image that doesn't clash: "gift.png", "gift-2.png"… */
function imageFileName(base, ext, existing) {
  const taken = new Set(existing.map((e) => e.toLowerCase()));
  let name = `${slug(base)}${ext}`;
  for (let i = 2; taken.has(name.toLowerCase()); i++) name = `${slug(base)}-${i}${ext}`;
  return name;
}

/** "2-5" -> [2, 3, 4, 5]; "3+" -> [3 … 8]; "2,4" -> [2, 4]. */
function playerCounts(players) {
  const out = new Set();
  for (const part of String(players || "").split(",")) {
    const m = part.trim().match(/^(\d+)(?:-(\d+)|(\+))?$/);
    if (!m) continue;
    const lo = +m[1], hi = m[2] ? +m[2] : m[3] ? Math.max(lo, 8) : lo;
    for (let n = lo; n <= hi; n++) out.add(n);
  }
  return [...out].sort((a, b) => a - b);
}

/**
 * The wishlist grouped by packs: [[wish, the wishes that are also in it]], for the wishes not inside another
 * one, sorted by priority (a pack takes the best priority of its parts), then name.
 */
function wishTree(wishes) {
  const key = (s) => fold(String(s || ""));
  const byName = new Map(wishes.map((w) => [key(w.name), w]));
  const parts = new Map(), inside = new Set();
  for (const w of wishes) {
    for (const pack of [].concat(w.in || [])) {
      const p = byName.get(key(pack));
      if (p && p !== w) {
        if (!parts.has(p)) parts.set(p, []);
        parts.get(p).push(w);
        inside.add(w);
      }
    }
  }
  const prio = (w) => Math.min(...[w, ...(parts.get(w) || [])].map((x) => (Number.isInteger(x.priority) ? x.priority : 99)));
  const order = (a, b) => prio(a) - prio(b) || key(a.name).localeCompare(key(b.name));
  return wishes.filter((w) => !inside.has(w)).sort(order).map((w) => [w, (parts.get(w) || []).sort(order)]);
}

module.exports = {
  severity, checkArgs, fmtArgs, previewArgs, expand, parseCheckOutput, issueColumns, fold,
  previewHtml, previewLink, imagePlacement, slug, imageFileName, playerCounts, wishTree,
};
