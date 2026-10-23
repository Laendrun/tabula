// Pure helpers for the Tabula extension: no `vscode` import, so they can be tested with plain node.
//
// The extension doesn't parse .game files itself: `tabula outline --json` does (the same parser as every
// other tabula command), and the functions below read its output. What is left here only looks at the
// line under the cursor (is it inside "[[", on a {=value}…) or at tabula's other outputs.
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

// ------------------------------------------------------------------ the outline (tabula outline --json)

const OUTLINE_VERSION = 1;

/** Arguments for `tabula outline` on the text of an editor (sent on stdin). */
function outlineArgs({ file, vault, extraArgs = [], stdin = true }) {
  const args = [...extraArgs];
  if (vault) args.push("--vault", vault);
  args.push("outline", file, "--json");
  if (stdin) args.push("--stdin");
  return args;
}

function parseOutline(stdout) {
  const start = stdout.indexOf("{");
  if (start < 0) throw new Error("tabula printed no outline (is it version 0.32 or newer?)");
  const o = JSON.parse(stdout.slice(start));
  if (o.outline !== OUTLINE_VERSION) throw new Error(`tabula's outline is version ${o.outline}, this extension reads ${OUTLINE_VERSION}: update both`);
  return o;
}

// The outline counts columns in characters (code points); VS Code in UTF-16 units (an emoji counts twice).
/** A column of the outline as a VS Code column on that line. */
function u16(lineText, cp) {
  let units = 0, n = 0;
  for (const ch of lineText) {
    if (n >= cp) break;
    units += ch.length;
    n++;
  }
  return units + Math.max(0, cp - n);
}

/** A VS Code column as a column of the outline. */
function cp(lineText, units) {
  return Array.from(lineText.slice(0, units)).length;
}

/** Every definition the file can refer to: its own, then the included fragments', then (a translation) the
 *  default-language file's. Each with `file` (null: this file). */
function allDefinitions(o) {
  const out = o.definitions.map((d) => ({ ...d, file: null }));
  for (const f of o.fragments || []) out.push(...f.definitions.map((d) => ({ ...d, file: f.file })));
  if (o.default) {
    out.push(...o.default.definitions.map((d) => ({ ...d, file: o.default.file })));
    for (const f of o.default.fragments || []) out.push(...f.definitions.map((d) => ({ ...d, file: f.file })));
  }
  return out;
}

function allComponents(o) {
  const out = o.components.map((c) => ({ ...c, file: null }));
  for (const f of o.fragments || []) out.push(...f.components.map((c) => ({ ...c, file: f.file })));
  if (o.default) out.push(...o.default.components.map((c) => ({ ...c, file: o.default.file })));
  return out;
}

const within = (x, line, col) => x.line === line && col >= x.start && col <= x.end;

/** The [[reference]] at a position (line, column in characters), or null. */
function refUnder(o, line, col) {
  return o.references.find((r) => within(r, line, col)) || null;
}

/** The ![[include]] on a line, or null. */
function includeUnder(o, line) {
  return o.includes.find((i) => i.line === line) || null;
}

/** The headings a [[#link]] points to: by title, else by role. */
function sectionTargets(o, ref) {
  const byTitle = o.headings.filter((h) => h.fold === ref.fold);
  const byRole = o.headings.filter((h) => h.roles.includes(ref.name.trim().toLowerCase()));
  return byTitle.length ? byTitle : byRole;
}

/** Where a reference points to: [{ file (null: this file), line }] — definitions first, then components. */
function targets(o, ref) {
  if (ref.section) return sectionTargets(o, ref).map((h) => ({ file: null, line: h.line }));
  const defs = allDefinitions(o).filter((d) => d.fold === ref.fold);
  if (defs.length) return defs.map((d) => ({ file: d.file, line: d.line }));
  return allComponents(o).filter((c) => c.fold === ref.fold).map((c) => ({ file: c.file, line: c.line }));
}

/** Markdown for one definition: its picture (`imageUrl(path)` makes it a link VS Code can show), fields, text. */
function definitionHover(d, imageUrl) {
  let pic = "";
  if (d.image) {
    if (d.image.url) pic = `![](${d.image.url}|height=160)`;
    else if (d.image.path && d.image.exists && imageUrl) pic = `![](${imageUrl(d.image.path)}|height=160)`;
    else pic = `*picture: ${d.image.src}*`;
  }
  return [`**${d.term}**${d.cond ? ` \`{${d.cond}}\`` : ""}`, pic, d.markdown].filter(Boolean).join("\n\n");
}

/** Markdown for hovering a reference, or null when it matches nothing. */
function hoverFor(o, ref, imageUrl) {
  if (ref.section) {
    const h = sectionTargets(o, ref)[0];
    if (!h) return null;
    return `**${h.key ? "★ " : ""}${h.title}**${h.cond ? ` \`{${h.cond}}\`` : ""}\n\n${h.preview}`.trim();
  }
  const defs = allDefinitions(o).filter((d) => d.fold === ref.fold);
  const comps = allComponents(o).filter((c) => c.fold === ref.fold && !c.file);
  if (!defs.length && !comps.length) return null;
  const parts = defs.map((d) => definitionHover(d, imageUrl));
  if (comps.length) parts.push(comps.map((c) => "- " + c.text).join("\n"));
  return parts.join("\n\n---\n\n");
}

/** What can go inside [[ ]]: terms (definitions first, then components), and sections and roles for [[#. */
function completionsFor(o) {
  const terms = [];
  const seen = new Set();
  for (const d of allDefinitions(o)) {
    if (seen.has(d.fold)) continue;
    seen.add(d.fold);
    terms.push({ label: d.term, kind: "definition", detail: d.cond ? `{${d.cond}}` : "", doc: d.markdown });
  }
  for (const c of allComponents(o)) {
    if (seen.has(c.fold)) continue;
    seen.add(c.fold);
    terms.push({ label: c.name, kind: "component", detail: `${c.quantity}x`, doc: c.text });
  }
  return { terms, sections: sectionItems(o.headings) };
}

function sectionItems(headings) {
  const out = [];
  for (const h of headings) {
    if (!h.title) continue;
    out.push({ label: h.title, kind: "section", detail: (h.key ? "★ " : "") + "#".repeat(h.level), doc: "" });
    for (const role of h.roles) out.push({ label: role, kind: "role", detail: `→ ${h.title}`, doc: "" });
  }
  return out;
}

/** Markdown preview of what an ![[include]] brings. */
function includeHover(inc) {
  if (!inc.file) return `No shared fragment \`${inc.name}\` (looked for _shared/${inc.name}.game)`;
  return `*from \`_shared/${inc.name}\`${inc.section ? ` — ${inc.section}` : ""}*\n\n${inc.preview || ""}`.trim();
}

/**
 * What is at a position for rename and "find all references": a [[reference]], a glossary term, a component
 * or a heading. { kind: "term" | "section", fold, name, start, end } (the name's columns on that line), or null.
 */
function targetAt(o, line, col) {
  const ref = refUnder(o, line, col);
  if (ref) {
    if (ref.section) {
      const h = o.headings.find((x) => x.fold === ref.fold);
      return h ? { kind: "section", fold: ref.fold, name: h.title, start: ref.name_start, end: ref.name_end, missing: false }
        : { kind: "section", fold: ref.fold, name: ref.name, start: ref.name_start, end: ref.name_end, missing: true };
    }
    const d = o.definitions.find((x) => x.fold === ref.fold);
    return { kind: "term", fold: ref.fold, name: ref.name, placeholder: d ? d.term : ref.name, start: ref.name_start, end: ref.name_end };
  }
  const d = o.definitions.find((x) => x.line === line);
  if (d) return { kind: "term", fold: d.fold, name: d.term, start: d.start, end: d.stop };
  const h = o.headings.find((x) => x.line === line);
  if (h && h.title) return { kind: "section", fold: h.fold, name: h.title, start: h.start, end: h.stop };
  return null;
}

/** Where what is at a position appears: { kind, name, definitions: [{line,start,end}], references: [...] }. */
function occurrencesAt(o, line, col) {
  const t = targetAt(o, line, col);
  if (!t) return null;
  const definitions = t.kind === "term"
    ? o.definitions.filter((d) => d.fold === t.fold).map((d) => ({ line: d.line, start: d.start, end: d.stop }))
    : o.headings.filter((h) => h.fold === t.fold).map((h) => ({ line: h.line, start: h.start, end: h.stop }));
  const references = o.references.filter((r) => r.section === (t.kind === "section") && r.fold === t.fold)
    .map((r) => ({ line: r.line, start: r.start, end: r.end }));
  return { name: t.name, kind: t.kind, definitions, references };
}

/** How often definitions (always) and headings (when linked to) are referred to: [{ line, kind, name, count }]. */
function useCounts(o) {
  const terms = new Map(), sections = new Map();
  for (const r of o.references) {
    const m = r.section ? sections : terms;
    m.set(r.fold, (m.get(r.fold) || 0) + 1);
  }
  const out = o.definitions.map((d) => ({ line: d.line, kind: "term", name: d.term, fold: d.fold, count: terms.get(d.fold) || 0 }));
  for (const h of o.headings) {
    const n = sections.get(h.fold) || 0;
    if (n && h.title) out.push({ line: h.line, kind: "section", name: h.title, fold: h.fold, count: n });
  }
  return out.sort((a, b) => a.line - b.line);
}

/** What F2 renames at a position (throws a message for the user when there's nothing to rename). */
function renameTarget(o, line, col) {
  const t = targetAt(o, line, col);
  if (!t) throw new Error("Put the cursor on a [[reference]], a glossary term or a heading to rename it");
  if (t.kind === "section" && t.missing) throw new Error("This links to a role or to no heading: nothing to rename");
  return t;
}

/**
 * The edits that rename what is at a position: its definition or heading and every reference to it.
 * [{ line, start, end, text }] (columns in characters), or throws with a message for the user.
 */
function renameEdits(o, line, col, newName) {
  newName = newName.trim();
  if (BAD_NAME.test(newName)) throw new Error("A name can't be empty or contain [ ] { } or |");
  const t = renameTarget(o, line, col);
  const edits = [];
  let oldName = t.name;
  if (t.kind === "term") {
    const defs = o.definitions.filter((d) => d.fold === t.fold);
    const comps = o.components.filter((c) => c.fold === t.fold);
    if (!defs.length && !comps.length) {
      throw new Error(`'${t.name}' isn't defined in this file (maybe in a shared fragment): rename it there`);
    }
    if (defs.length) oldName = defs[0].term;
    for (const d of defs) edits.push({ line: d.line, start: d.start, end: d.stop, text: newName });
  } else {
    for (const h of o.headings.filter((x) => x.fold === t.fold)) edits.push({ line: h.line, start: h.start, end: h.stop, text: newName });
  }
  const prefix = t.kind === "section" ? "#" : "";
  for (const r of o.references) {
    if (r.section !== (t.kind === "section") || r.fold !== t.fold) continue;
    edits.push({ line: r.line, start: r.start, end: r.end,
                 text: renamedRef(r.name, r.alias === null ? undefined : r.alias, oldName, newName, prefix) });
  }
  return edits;
}

/** The frontmatter key being typed at a position: { level, start, present }, or null (not in the frontmatter). */
function frontmatterContext(o, lineText, line, column) {
  const fm = o.frontmatter;
  if (!fm || line < fm.start || line > fm.end) return null;
  const m = lineText.slice(0, column).match(/^(\s*)([\w-]*)$/);
  if (!m) return null;
  const indent = m[1].length;
  if (indent === 0) {
    return { level: "top", start: 0, present: fm.keys.filter((k) => k.level === "top" && k.line !== line).map((k) => k.key) };
  }
  // under an extension or a variant (extensions: → name: → here), when no top-level key comes in between
  const opt = [...fm.options].reverse().find((x) => x.line < line && indent > x.indent);
  if (!opt || fm.keys.some((k) => k.level === "top" && k.line > opt.line && k.line <= line)) return null;
  const present = fm.keys.filter((k) => k.option === opt.name && k.line !== line).map((k) => k.key);
  return { level: "option", start: indent, present };
}

/** The frontmatter key under the cursor: { level, key, start, end }, or null. */
function frontmatterKeyAt(o, line, col) {
  const k = o.frontmatter && o.frontmatter.keys.find((x) => within(x, line, col));
  return k ? { level: k.level, key: k.key, start: k.start, end: k.end } : null;
}

/** The clickable path at a position (an image or a fragment), or null. */
function linkAt(o, line, col) {
  return o.links.find((l) => within(l, line, col)) || null;
}

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

// ------------------------------------------------------------------ the line under the cursor

/** The [[reference]] under the cursor (column, 0-based) on a line, or null. */
function refAt(lineText, column) {
  const re = /\[\[([^\]|]+)(?:\|[^\]]*)?\]\]/g;
  let m;
  while ((m = re.exec(lineText))) {
    if (column >= m.index && column <= m.index + m[0].length) {
      return { name: m[1].trim(), start: m.index, end: m.index + m[0].length };
    }
  }
  return null;
}

const INCLUDE_LINE = /^(\s*)!\[\[([^\[\]#|\n]+?)(?:#([^\[\]|\n]+))?\]\]\s*$/;

/** The `![[fragment#Section]]` line under the cursor, or null. */
function includeAt(lineText, column) {
  const m = lineText.match(INCLUDE_LINE);
  if (!m) return null;
  const start = m[1].length;
  const end = lineText.trimEnd().length;
  if (column < start || column > end) return null;
  return { name: m[2].trim(), section: m[3] ? m[3].trim() : null, start, end };
}

/** Is the cursor in an unfinished `![[name` or `![[name#Section`? */
function includeContext(lineText, column) {
  const before = lineText.slice(0, column);
  const m = before.match(/^\s*!\[\[([^\[\]#|]*)(?:#([^\[\]|]*))?$/);
  if (!m) return null;
  const typed = m[2] !== undefined ? m[2] : m[1];
  return {
    name: m[1].trim(),
    section: m[2] !== undefined ? m[2] : null,
    start: column - typed.length,
    closed: /^[^\[\]\n]*\]\]/.test(lineText.slice(column)),
  };
}

/**
 * Is the cursor inside an unfinished "[[…"? Returns where the typed name starts, whether it is a section
 * link ("[[#…"), what was typed, and whether "]]" already follows (so it isn't added twice).
 */
function completionContext(lineText, column) {
  const m = lineText.slice(0, column).match(/\[\[(#?)([^\[\]|]*)$/);
  if (!m) return null;
  return {
    section: m[1] === "#",
    typed: m[2],
    start: column - m[2].length,
    closed: /^[^\[\]\n]*\]\]/.test(lineText.slice(column)),
  };
}

/** Typing a value name after "{=": { typed, start, closed }, or null. */
function valueContext(lineText, column) {
  const m = lineText.slice(0, column).match(/(?<!\\)\{=\s*([\w-]*)$/);
  if (!m) return null;
  return { typed: m[1], start: column - m[1].length, closed: /^[\w-]*\s*\}/.test(lineText.slice(column)) };
}

/** The {=name} under the cursor: { name, start, end }, or null. */
function valueAt(lineText, column) {
  for (const m of lineText.matchAll(/(?<!\\)\{=\s*([\w-]+)\s*\}/g)) {
    if (column >= m.index && column <= m.index + m[0].length) return { name: m[1], start: m.index, end: m.index + m[0].length };
  }
  return null;
}

/** Typing a symbol name after ":" (at least one letter): { typed, start } (start: the ":"), or null. */
function symbolContext(lineText, column) {
  const m = lineText.slice(0, column).match(/(?<![\p{L}_:\\/]):([A-Za-z][\w+-]*)$/u);   // not "10:3"
  return m ? { typed: m[1], start: column - m[1].length - 1, closed: lineText[column] === ":" } : null;
}

/** The :name: under the cursor: { name, start, end }, or null. */
function symbolAt(lineText, column) {
  for (const m of lineText.matchAll(/(?<![\p{L}_:\\/]):([A-Za-z][\w+-]*):(?![\w:/])/gu)) {
    if (column >= m.index && column <= m.index + m[0].length) return { name: m[1], start: m.index, end: m.index + m[0].length };
  }
  return null;
}

// ------------------------------------------------------------------ preview, rename, quick fixes

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

const BAD_NAME = /[\[\]{}|\n]|^\s*$/;

/** A reference rewritten for a renamed term or section: alias, case and plurals of the old text are kept. */
function renamedRef(name, alias, oldName, newName, prefix) {
  if (alias !== undefined) return `[[${prefix}${newName}|${alias}]]`;
  if (name === oldName) return `[[${prefix}${newName}]]`;
  if (name.toLowerCase() === oldName.toLowerCase()) {          // "[[bateau]]" for the term "Bateau"
    const first = name[0] === name[0].toLowerCase() ? newName[0].toLowerCase() : newName[0].toUpperCase();
    return `[[${prefix}${first}${newName.slice(1)}]]`;
  }
  return `[[${prefix}${newName}|${name}]]`;                     // "[[bateaux]]": the text stays as written
}

/** Edit distance between two folded names (for "did you mean"). */
function distance(a, b) {
  const row = Array.from({ length: b.length + 1 }, (_, j) => j);
  for (let i = 1; i <= a.length; i++) {
    let prev = row[0];
    row[0] = i;
    for (let j = 1; j <= b.length; j++) {
      const cur = row[j];
      row[j] = Math.min(row[j] + 1, row[j - 1] + 1, prev + (a[i - 1] === b[j - 1] ? 0 : 1));
      prev = cur;
    }
  }
  return row[b.length];
}

/** The names closest to `name` (up to 3), for a reference that matches nothing. */
function closest(name, names) {
  const key = fold(name);
  const seen = new Set();
  return names
    .filter((n) => !seen.has(fold(n)) && seen.add(fold(n)))
    .map((n) => ({ n, d: distance(key, fold(n)) }))
    .filter((x) => x.d > 0 && x.d <= Math.max(2, Math.floor(key.length / 3)))
    .sort((a, b) => a.d - b.d)
    .slice(0, 3)
    .map((x) => x.n);
}

/**
 * Quick fixes for one tabula issue. `range` is where the squiggle is ({ start, end } columns on `line`);
 * `names` are the terms and components the file can use (included fragments too); `sections` its headings;
 * `glossaryLine` where a new term goes (the outline's glossary_line, -1 for none).
 * Returns [{ title, edits: [{ line, start, end, text }], preferred?, addWord? }].
 */
function quickFixes(text, line, message, range, names = [], sections = [], glossaryLine = -1) {
  const lines = text.replace(/\r\n?/g, "\n").split("\n");
  const lt = lines[line] || "";
  const out = [];
  let m;
  if ((m = message.match(/^unknown word '(.+?)'(?: \(did you mean '(.+?)'\?\))?$/))) {
    const word = m[1];
    if (m[2]) {
      const fix = word[0] === word[0].toUpperCase() ? m[2][0].toUpperCase() + m[2].slice(1) : m[2];
      out.push({ title: `Change to '${fix}'`, edits: [{ line, start: range.start, end: range.end, text: fix }], preferred: true });
    }
    const plain = word.includes("'") ? word.split("'").pop() : word;    // "d'Eveline": add "Eveline"
    out.push({ title: `Add '${plain}' to words.txt`, edits: [], addWord: plain });
  } else if ((m = message.match(/^'(.+?):' in frontmatter: did you mean '(.+?)'\?/))) {
    const k = lines.findIndex((l, i) => i > 0 && i < 200 && l.startsWith(m[1] + ":"));
    if (k > 0) out.push({ title: `Change to '${m[2]}:'`, edits: [{ line: k, start: 0, end: m[1].length, text: m[2] }], preferred: true });
  } else if ((m = message.match(/^role '#(.+?)': did you mean '#(.+?)'\?/))) {
    const at = lt.search(new RegExp(`#${m[1].replace(/[-]/g, "\\-")}(?![\\w-])`));
    if (at >= 0) out.push({ title: `Change to '#${m[2]}'`, edits: [{ line, start: at + 1, end: at + 1 + m[1].length, text: m[2] }], preferred: true });
  } else if ((m = message.match(/^'\[(.+?)\]' has single brackets/))) {
    const at = lt.indexOf(`[${m[1]}]`);
    if (at >= 0) out.push({ title: `Change to [[${m[1]}]]`, edits: [{ line, start: at, end: at + m[1].length + 2, text: `[[${m[1]}]]` }], preferred: true });
  } else if ((m = message.match(/^(\[\[(#?)([^\]|]+?)(?:\|([^\]]*))?\]\]) matches no/))) {
    const [, raw, hash, name, alias] = m;
    const at = lt.indexOf(raw);
    if (at < 0) return out;
    const pool = hash ? sections : names;
    for (const c of closest(name.trim(), pool)) {
      out.push({ title: `Change to [[${hash}${c}]]`, edits: [{ line, start: at, end: at + raw.length, text: `[[${hash}${c}${alias !== undefined ? "|" + alias : ""}]]` }] });
    }
    if (out.length === 1) out[0].preferred = true;
    const g = hash ? -1 : glossaryLine;
    if (g >= 0) {
      const term = name.trim()[0].toUpperCase() + name.trim().slice(1);
      const before = g > 0 && lines[g - 1].trim() ? "\n" : "";
      out.push({ title: `Define '${term}' in the glossary`, edits: [{ line: g, start: 0, end: 0, text: `${before}${term}\n: \n\n` }] });
    }
  }
  return out;
}

// ------------------------------------------------------------------ frontmatter keys, images, sidebar

/** Keys a schema defines at a level: [{ key, description }]. `schemas`: { game, sheet } (the JSON Schemas). */
function schemaKeys(schemas, kind, level) {
  const root = kind === "sheet" ? schemas.sheet : schemas.game;
  if (!root) return [];
  let props = root.properties || {};
  if (level === "option") {
    const opt = ((((root.properties || {}).extensions || {}).oneOf || [])[1] || {}).additionalProperties || {};
    props = ((opt.oneOf || []).find((o) => o.type === "object") || {}).properties || {};
  } else if (level !== "top") return [];
  return Object.entries(props).map(([key, v]) => ({ key, description: v.description || "" }));
}

/** The hover of a frontmatter key: what the spec says it does, or that it is your own. */
function frontmatterHover(schemas, kind, level, key) {
  const known = schemaKeys(schemas, kind, level).find((k) => k.key === key);
  if (known) return `**${key}**${known.description ? ` — ${known.description}` : ""}`;
  const label = key.replace(/_/g, " ");
  const shown = label === label.toLowerCase() ? label[0].toUpperCase() + label.slice(1) : label;
  if (kind === "sheet") return `**${key}** — not a sheet setting: tabula ignores it.`;
  return `**${key}** — your own ${level === "option" ? "detail" : "key"}: shown as “${shown}: …”` +
    (level === "option" ? " with the extension or variant." : " on the game's page and in `tabula show`.");
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
  severity, checkArgs, fmtArgs, previewArgs, outlineArgs, parseOutline, expand, parseCheckOutput, issueColumns, fold,
  u16, cp, allDefinitions, allComponents, refUnder, includeUnder, targets, hoverFor, definitionHover, completionsFor,
  sectionItems, includeHover, targetAt, occurrencesAt, useCounts, renameTarget, renameEdits, frontmatterContext,
  frontmatterKeyAt, linkAt, imagePlacement,
  refAt, includeAt, includeContext, completionContext, valueContext, valueAt, symbolContext, symbolAt,
  previewHtml, previewLink, renamedRef, closest, quickFixes,
  schemaKeys, frontmatterHover, slug, imageFileName, playerCounts, wishTree,
};
