// Pure helpers for the Tabula extension: no `vscode` import, so they can be tested with plain node.
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
    .map((w) => (w.length > 3 && /[sx]$/.test(w) && !w.endsWith("ss") ? w.slice(0, -1) : w))
    .join(" ");
}

const HEADING = /^(#{1,6})\s+(.*?)\s*$/;
const ATTRS_END = /\s*\{([^{}]*)\}\s*$/;
const COND_START = /^\{([^{}]*)\}\s*/;
const COMPONENT = /^\s*[-*+]\s+(?:\{[^{}]*\}\s*)?(\d+(?:-\d+)?)\s*[x×X]\s+[^\[\]\n]*?\[\[([^\]|]+)/;
const END_MARK = /^-{3,}\s*$/;
const DEF_LINE = /^:(\s|$)/;

/** Lines that aren't rules text: the frontmatter, code blocks and comments (true = skip). */
function skippedLines(lines) {
  const skip = new Array(lines.length).fill(false);
  let i = 0;
  if (lines[0] !== undefined && lines[0].trim() === "---") {
    const end = lines.findIndex((l, k) => k > 0 && l.trim() === "---");
    if (end > 0) for (let k = 0; k <= end; k++) skip[k] = true;
    i = end > 0 ? end + 1 : 0;
  }
  let fence = null;
  let comment = false;
  for (let k = i; k < lines.length; k++) {
    const t = lines[k];
    if (comment) {
      skip[k] = true;
      if (t.includes("-->")) comment = false;
      continue;
    }
    const f = t.match(/^\s*(```|~~~)/);
    if (fence) {
      skip[k] = true;
      if (f && t.trim().startsWith(fence)) fence = null;
      continue;
    }
    if (f) {
      fence = f[1];
      skip[k] = true;
      continue;
    }
    if (t.trimStart().startsWith("<!--") && !t.includes("-->")) {
      comment = true;
      skip[k] = true;
    }
  }
  return skip;
}

/**
 * Outline of a .game file: headings (with their end line), definitions and components.
 * Lines are 0-based. Skips the frontmatter, code blocks and comments.
 */
function outline(text) {
  const lines = text.replace(/\r\n?/g, "\n").split("\n");
  const skip = skippedLines(lines);
  const headings = [];
  const definitions = [];
  const components = [];
  const ends = [];
  for (let k = 0; k < lines.length; k++) {
    if (skip[k]) continue;
    const t = lines[k];
    let m;
    if ((m = t.match(HEADING))) {
      let title = m[2];
      let attrs = "";
      const key = title.startsWith("!") && !title.startsWith("![");      // "## ! Title": a key section
      if (key) title = title.slice(1).trimStart();
      const a = title.match(ATTRS_END);
      if (a) {
        attrs = a[1];
        title = title.slice(0, a.index);
      }
      headings.push({ level: m[1].length, title: title.trim(), attrs, key, line: k, end: lines.length - 1 });
    } else if (END_MARK.test(t)) {
      ends.push(k);
    } else if ((m = t.match(COMPONENT))) {
      components.push({ name: m[2].trim(), quantity: m[1], line: k });
    } else if (t.trim() && k + 1 < lines.length && !skip[k + 1] && DEF_LINE.test(lines[k + 1]) && !/^\s/.test(t)
               && !/^([-*+>|!#:]|\d+[.)]\s)/.test(t.trim())) {
      let term = t.trim();
      let cond = "";
      const c1 = term.match(COND_START);
      if (c1) {
        cond = c1[1];
        term = term.slice(c1[0].length);
      }
      const c2 = term.match(ATTRS_END);
      if (c2) {
        cond = cond || c2[1];
        term = term.slice(0, c2.index);
      }
      let last = k + 1;
      while (last + 1 < lines.length && (DEF_LINE.test(lines[last + 1]) || /^\s+\S/.test(lines[last + 1])
             || (!lines[last + 1].trim() && last + 2 < lines.length && /^(\s+\S|:(\s|$))/.test(lines[last + 2])))) {
        last++;
      }
      definitions.push({ term: term.trim(), cond, line: k, end: last });
    }
  }
  // a heading's section ends before the next heading of the same or a higher level, or at its "---"
  for (let h = 0; h < headings.length; h++) {
    const H = headings[h];
    const next = headings.slice(h + 1).find((x) => x.level <= H.level);
    let end = next ? next.line - 1 : lines.length - 1;
    // each "---" closes the innermost open section: deeper ones first, then this one
    const open = [];
    let k = h + 1;
    for (let line = H.line + 1; line <= end; line++) {
      while (k < headings.length && headings[k].line === line) {
        while (open.length && open[open.length - 1] >= headings[k].level) open.pop();
        open.push(headings[k].level);
        k++;
      }
      if (ends.includes(line)) {
        if (!open.length) {
          end = line;
          break;
        }
        open.pop();
      }
    }
    while (end > H.line && !lines[end].trim()) end--;
    H.end = end;
  }
  return { headings, definitions, components };
}

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

/**
 * Where a reference points to: its definitions first, then the component lines that name it.
 * [[#Section]] points to the heading with that title (matched like references), else the heading with that role.
 */
function findTargets(text, name) {
  const o = outline(text);
  if (name.startsWith("#")) {
    const want = name.slice(1).trim();
    const byTitle = o.headings.filter((h) => fold(h.title) === fold(want));
    const byRole = o.headings.filter((h) => h.attrs.split(/\s+/).includes("#" + want.toLowerCase()));
    return (byTitle.length ? byTitle : byRole).map((h) => h.line);
  }
  const key = fold(name);
  const defs = o.definitions.filter((d) => fold(d.term) === key).map((d) => d.line);
  const comps = o.components.filter((c) => fold(c.name) === key).map((c) => c.line);
  return defs.length ? defs : comps;
}

/** Text without reference brackets: "[[a|b]]" -> "b", "[[a]]" -> "a" (for labels and hovers). */
function plainRefs(text) {
  return text.replace(/\[\[#?([^\]|]+)(?:\|([^\]]*))?\]\]/g, (_, name, shown) => (shown || name).trim());
}

/** The body of a definition as plain lines: the ": " markers and the common indentation removed. */
function definitionBody(lines, def) {
  const body = [];
  for (let k = def.line + 1; k <= def.end; k++) {
    body.push(lines[k].replace(/^:(\s|$)/, "  "));
  }
  const indent = Math.min(...body.filter((l) => l.trim()).map((l) => l.match(/^\s*/)[0].length), 99);
  return body.map((l) => l.slice(Math.min(indent, l.length))).join("\n").replace(/^\n+|\n+$/g, "");
}

/** A definition body as Markdown: "key:: value" fields at the top become bold lines, references plain text. */
function definitionMarkdown(body, imageUrl) {
  const lines = body.split("\n");
  const fields = [];
  let picture = "";
  while (lines.length && /^[^\W\d][\w -]*?::\s?/u.test(lines[0])) {
    let [, key, value] = lines.shift().match(/^([^\W\d][\w -]*?)::\s?(.*)$/u);
    while (lines.length && /^\s+\S/.test(lines[0])) value += " " + lines.shift().trim();   // indented: continues
    if (key.trim() === "image") {            // the card's picture
      picture = imageUrl ? `![](${imageUrl(value.trim())}|height=160)` : `*picture: ${value.trim()}*`;
      continue;
    }
    fields.push(`**${key.trim()}:** ${plainRefs(value.trim())}`);
  }
  const rest = plainRefs(lines.join("\n")).trim();
  return [picture, fields.join("  \n"), rest].filter(Boolean).join("\n\n");
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

/** Markdown preview of what `![[name#section]]` includes (the section, or the fragment's sections). */
function includeHover(text, name, section) {
  if (section) {
    const h = hoverText(text, "#" + section);
    return h ? `*from \`_shared/${name}\`*\n\n${h}` : null;
  }
  const o = outline(text);
  const heads = o.headings.map((h) => `${"  ".repeat(h.level - 1)}- ${plainRefs(h.title)}`).join("\n");
  return `**Fragment \`${name}\`**${heads ? `\n\n${heads}` : ""}`;
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

/**
 * What can go inside [[ ]] in a game: its terms (definitions first, then components without a definition)
 * and, for [[#…]], its section titles and roles. Each item: { label, kind, detail, doc }.
 */
function completions(text) {
  const lines = text.replace(/\r\n?/g, "\n").split("\n");
  const o = outline(text);
  const terms = [];
  const seen = new Set();
  for (const d of o.definitions) {
    const key = fold(d.term);
    if (seen.has(key)) continue;
    seen.add(key);
    terms.push({ label: d.term, kind: "definition", detail: d.cond ? `{${d.cond}}` : "",
                 doc: definitionMarkdown(definitionBody(lines, d)) });
  }
  for (const c of o.components) {
    const key = fold(c.name);
    if (seen.has(key)) continue;
    seen.add(key);
    terms.push({ label: c.name, kind: "component", detail: `${c.quantity}x`,
                 doc: plainRefs(lines[c.line].trim().replace(/^[-*+]\s+/, "")) });
  }
  const sections = [];
  for (const h of o.headings) {
    const title = plainRefs(h.title);
    if (!title) continue;
    sections.push({ label: title, kind: "section", detail: (h.key ? "★ " : "") + "#".repeat(h.level), doc: "" });
    for (const role of (h.attrs.match(/#[\w-]+/g) || [])) {
      sections.push({ label: role.slice(1), kind: "role", detail: `→ ${title}`, doc: "" });
    }
  }
  return { terms, sections };
}

/** Markdown for hovering a [[reference]] (name as written, with or without "#"), or null if it matches nothing. */
function hoverText(text, name, imageUrl) {
  const lines = text.replace(/\r\n?/g, "\n").split("\n");
  const o = outline(text);
  if (name.startsWith("#")) {
    const target = findTargets(text, name)[0];
    if (target === undefined) return null;
    const h = o.headings.find((x) => x.line === target);
    const body = lines.slice(h.line + 1, Math.min(h.end, h.line + 12) + 1).join("\n").trim();
    const more = h.end > h.line + 12 ? "\n\n…" : "";
    return `**${h.key ? "★ " : ""}${plainRefs(h.title)}**${h.attrs ? ` \`{${h.attrs}}\`` : ""}\n\n${plainRefs(body)}${more}`.trim();
  }
  const key = fold(name);
  const defs = o.definitions.filter((d) => fold(d.term) === key);
  const comps = o.components.filter((c) => fold(c.name) === key);
  if (!defs.length && !comps.length) return null;
  const parts = defs.map((d) => `**${d.term}**${d.cond ? ` \`{${d.cond}}\`` : ""}\n\n${definitionMarkdown(definitionBody(lines, d), imageUrl)}`);
  if (comps.length) {
    parts.push(comps.map((c) => "- " + plainRefs(lines[c.line].trim().replace(/^[-*+]\s+/, ""))).join("\n"));
  }
  return parts.join("\n\n---\n\n");
}

/** The lines of a fragment's section (title matched like references, or a role), without its heading. */
function fragmentSection(text, section) {
  const lines = text.replace(/\r\n?/g, "\n").split("\n");
  const want = fold(section);
  const role = "#" + section.trim().toLowerCase();
  const heads = outline(text).headings;
  const h = heads.find((x) => fold(x.title) === want) || heads.find((x) => x.attrs.split(/\s+/).includes(role));
  return h ? lines.slice(h.line + 1, h.end + 1).join("\n") : null;
}

/**
 * The text with every `![[fragment#Section]]` line replaced by what it includes (for autocomplete and
 * hovers, which need the terms a fragment brings). `read(name)` returns a fragment's text, or null.
 */
function expandIncludes(text, read, depth = 0) {
  if (depth > 8) return text;
  return text.replace(/\r\n?/g, "\n").split("\n").map((line) => {
    const m = line.match(INCLUDE_LINE);
    if (!m) return line;
    const frag = read(m[2].trim());
    if (frag === null || frag === undefined) return line;
    const body = m[3] ? fragmentSection(frag, m[3].trim()) : frag.replace(/^---\n[\s\S]*?\n---\n/, "");
    return body === null ? line : expandIncludes(body, read, depth + 1);
  }).join("\n");
}

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

// ------------------------------------------------------------------ rename (F2)

const REF_ALL = /(?<!\\)\[\[([^\[\]|\n]+?)(?:\|([^\[\]\n]+?))?\]\]/g;
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

/**
 * What F2 renames at a position: a [[reference]], a glossary term, a component, or a heading.
 * Returns { kind: "term" | "section", name, start, end } (the range of the name on that line), or throws.
 */
function renameTarget(text, line, column) {
  const lines = text.replace(/\r\n?/g, "\n").split("\n");
  const lt = lines[line] || "";
  const o = outline(text);
  const ref = refAt(lt, column);
  if (ref) {
    const at = lt.indexOf(ref.name, ref.start);
    if (ref.name.startsWith("#")) {
      const want = fold(ref.name.slice(1));
      const h = o.headings.find((x) => fold(x.title) === want);
      if (!h) throw new Error(`${lt.slice(ref.start, ref.end)} links to a role or to no heading: nothing to rename`);
      return { kind: "section", name: h.title, start: at + 1, end: at + ref.name.length };
    }
    const def = o.definitions.find((x) => fold(x.term) === fold(ref.name));
    return { kind: "term", name: ref.name, placeholder: def ? def.term : ref.name, start: at, end: at + ref.name.length };
  }
  const d = o.definitions.find((x) => x.line === line);
  if (d) {
    const at = lt.indexOf(d.term);
    return { kind: "term", name: d.term, start: at, end: at + d.term.length };
  }
  const h = o.headings.find((x) => x.line === line);
  if (h && h.title) {
    const at = lt.indexOf(h.title, lt.indexOf("#") + h.level);
    return { kind: "section", name: h.title, start: at, end: at + h.title.length };
  }
  throw new Error("Put the cursor on a [[reference]], a glossary term or a heading to rename it");
}

/**
 * The edits that rename what is at (line, column): its definition or heading and every reference to it.
 * Returns [{ line, start, end, text }], or throws with a message for the user.
 */
function renameEdits(text, line, column, newName) {
  newName = newName.trim();
  if (BAD_NAME.test(newName)) throw new Error("A name can't be empty or contain [ ] { } or |");
  const target = renameTarget(text, line, column);
  const lines = text.replace(/\r\n?/g, "\n").split("\n");
  const skip = skippedLines(lines);
  const o = outline(text);
  const key = fold(target.name);
  const edits = [];
  let oldName = target.name;
  if (target.kind === "term") {
    const defs = o.definitions.filter((d) => fold(d.term) === key);
    const comps = o.components.filter((c) => fold(c.name) === key);
    if (!defs.length && !comps.length) {
      throw new Error(`'${target.name}' isn't defined in this file (maybe in a shared fragment): rename it there`);
    }
    if (defs.length) oldName = defs[0].term;
    for (const d of defs) {
      const at = lines[d.line].indexOf(d.term);
      edits.push({ line: d.line, start: at, end: at + d.term.length, text: newName });
    }
  } else {
    for (const h of o.headings.filter((x) => fold(x.title) === key)) {
      const at = lines[h.line].indexOf(h.title, lines[h.line].indexOf("#") + h.level);
      edits.push({ line: h.line, start: at, end: at + h.title.length, text: newName });
    }
  }
  const prefix = target.kind === "section" ? "#" : "";
  for (let k = 0; k < lines.length; k++) {
    if (skip[k]) continue;
    const code = [...lines[k].matchAll(/`[^`\n]*`/g)].map((c) => [c.index, c.index + c[0].length]);
    for (const m of lines[k].matchAll(REF_ALL)) {
      if (code.some(([a, b]) => m.index >= a && m.index < b)) continue;       // `[[x]]` in code
      let name = m[1].trim();
      if (prefix ? !name.startsWith("#") : name.startsWith("#")) continue;
      if (prefix) name = name.slice(1).trim();
      if (fold(name) !== key) continue;
      edits.push({ line: k, start: m.index, end: m.index + m[0].length, text: renamedRef(name, m[2], oldName, newName, prefix) });
    }
  }
  return edits;
}

// ------------------------------------------------------------------ quick fixes

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

/** Where a new glossary term goes: after the glossary's own text, before its sub-sections. */
function glossaryInsertLine(text) {
  const o = outline(text);
  const g = o.headings.find((h) => h.attrs.split(/\s+/).includes("#glossary"))
    || o.headings.find((h) => /^(glossary|glossaire|glossar|glosario|glossario)$/i.test(h.title));
  if (!g) return -1;
  const sub = o.headings.find((h) => h.line > g.line && h.line <= g.end && h.level > g.level);
  return sub ? sub.line : g.end + 1;
}

/**
 * Quick fixes for one tabula issue. `range` is where the squiggle is ({ start, end } columns on `line`);
 * `names` are the terms and components the file can use (included fragments too); `sections` its headings.
 * Returns [{ title, edits: [{ line, start, end, text }], preferred?, addWord? }].
 */
function quickFixes(text, line, message, range, names = [], sections = []) {
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
    const g = hash ? -1 : glossaryInsertLine(text);
    if (g >= 0) {
      const term = name.trim()[0].toUpperCase() + name.trim().slice(1);
      const before = g > 0 && lines[g - 1].trim() ? "\n" : "";
      out.push({ title: `Define '${term}' in the glossary`, edits: [{ line: g, start: 0, end: 0, text: `${before}${term}\n: \n\n` }] });
    }
  }
  return out;
}

// ------------------------------------------------------------------ values {=name} (and other named lists in YAML)

/** The frontmatter of a .game text, or the whole text for a .yaml file. */
function yamlPart(text) {
  const lines = text.replace(/\r\n?/g, "\n").split("\n");
  if (lines[0] !== undefined && lines[0].trim() === "---") {
    const end = lines.findIndex((l, k) => k > 0 && (l.trim() === "---" || l.trim() === "..."));
    return { lines: end > 0 ? lines.slice(0, end) : [], offset: 0 };
  }
  return { lines, offset: 0 };
}

/**
 * The entries under a top-level YAML key (values:, symbols:), written one per line:
 *   values:
 *     main: {2p: 7, "*": 5}
 *     hand:
 *       2p: 7
 * Returns [{ name, value, line }] (value: the text after "name:", or its indented lines joined with ", ").
 */
function yamlEntries(text, key) {
  const { lines } = yamlPart(text);
  const start = lines.findIndex((l) => new RegExp(`^${key}:\\s*(#.*)?$`).test(l));
  if (start < 0) return [];
  const out = [];
  let indent = null;
  for (let k = start + 1; k < lines.length; k++) {
    const l = lines[k];
    if (!l.trim() || l.trim().startsWith("#")) continue;
    const ind = l.length - l.trimStart().length;
    if (ind === 0) break;
    if (indent === null) indent = ind;
    const m = l.match(/^\s*("?)([^":#]+?)\1\s*:\s*(.*?)\s*$/);
    if (m) m[3] = m[3].replace(/\s+#.*$/, "");                // a comment after the value
    if (ind === indent && m) out.push({ name: m[2].trim(), value: m[3], line: k });
    else if (ind > indent && out.length && m) {
      const last = out[out.length - 1];
      last.value = (last.value ? last.value + ", " : "") + `${m[2].trim()}: ${m[3]}`;
    }
  }
  return out;
}

/** The values a game can use: the vault's, then its own (which win). [{ name, value, from }] */
function valuesOf(gameText, vaultYaml) {
  const byName = new Map();
  for (const e of yamlEntries(vaultYaml || "", "values")) byName.set(e.name, { ...e, from: "vault.yaml" });
  for (const e of yamlEntries(gameText, "values")) byName.set(e.name, { ...e, from: "this game" });
  return [...byName.values()];
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

// ------------------------------------------------------------------ symbols :name:

const IMAGE_EXT = /\.(png|jpe?g|gif|svg|webp)$/i;

/** A symbol's definition as written in YAML: "⭐", "media/gold.png" or "{image: media/key.png, text: 🔑}". */
function symbolParts(raw) {
  const unq = (s) => (s || "").trim().replace(/^(["'])(.*)\1$/, "$2");
  const m = raw.match(/^\{(.*)\}$/);
  if (m) {
    const image = (m[1].match(/image\s*:\s*("[^"]*"|'[^']*'|[^,}]+)/) || [])[1];
    const text = (m[1].match(/text\s*:\s*("[^"]*"|'[^']*'|[^,}]+)/) || [])[1];
    return { image: image ? unq(image) : null, text: text ? unq(text) : null };
  }
  const v = unq(raw);
  if (IMAGE_EXT.test(v) && !/^https?:/.test(v)) return { image: v, text: null };
  return { image: null, text: v };
}

/** The symbols a game can use: the vault's, then its own. [{ name, image, text, from }] */
function symbolsOf(gameText, vaultYaml) {
  const byName = new Map();
  for (const e of yamlEntries(vaultYaml || "", "symbols")) byName.set(e.name, { name: e.name, ...symbolParts(e.value), from: "vault.yaml" });
  for (const e of yamlEntries(gameText, "symbols")) byName.set(e.name, { name: e.name, ...symbolParts(e.value), from: "this game" });
  return [...byName.values()];
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

module.exports = {
  severity, checkArgs, fmtArgs, previewArgs, expand, parseCheckOutput, issueColumns, fold, outline, refAt, findTargets,
  plainRefs, definitionBody, definitionMarkdown, completionContext, completions, hoverText,
  includeAt, includeContext, includeHover,
  fragmentSection, expandIncludes, previewHtml, previewLink,
  yamlEntries, valuesOf, valueContext, valueAt, symbolParts, symbolsOf, symbolContext, symbolAt,
  skippedLines, renameTarget, renameEdits, quickFixes, closest, glossaryInsertLine,
};
