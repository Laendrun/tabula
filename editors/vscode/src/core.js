// Pure helpers for the Tabula extension: no `vscode` import, so they can be tested with plain node.
"use strict";

/** Command-line arguments for `tabula check` (file = the file being edited, or none for the whole vault). */
function checkArgs({ file, vault, extraArgs = [], definitions = false, stdin = false }) {
  const args = [...extraArgs];
  if (vault) args.push("--vault", vault);
  args.push("check");
  if (file) args.push(file);
  args.push("--json");
  if (stdin) args.push("--stdin");
  if (definitions) args.push("--definitions");
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
  const patterns = [/\[\[[^\]]*\]\]?/g, /\{[^{}]*\}/g, /'([^']+)'/g, /"([^"]+)"/g, /‘([^’]+)’/g];
  for (const re of patterns) {
    for (const m of message.matchAll(re)) candidates.push(m[1] !== undefined ? m[1] : m[0]);
  }
  for (const c of candidates) {
    if (!c.trim()) continue;
    let at = lineText.indexOf(c);
    if (at < 0) at = lineText.toLowerCase().indexOf(c.toLowerCase());
    if (at >= 0) return [at, at + c.length];
  }
  const first = lineText.search(/\S/);
  return first < 0 ? [0, lineText.length] : [first, lineText.trimEnd().length];
}

/** VS Code severity for a tabula issue level: TODO reminders are information, not warnings. */
function severity(level, S) {
  return level === "error" ? S.Error : level === "todo" ? S.Information : S.Warning;
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

/**
 * Outline of a .game file: headings (with their end line), definitions and components.
 * Lines are 0-based. Skips the frontmatter, code blocks and comments.
 */
function outline(text) {
  const lines = text.replace(/\r\n?/g, "\n").split("\n");
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
function definitionMarkdown(body) {
  const lines = body.split("\n");
  const fields = [];
  while (lines.length && /^[^\W\d][\w -]*?::\s?/u.test(lines[0])) {
    const [, key, value] = lines.shift().match(/^([^\W\d][\w -]*?)::\s?(.*)$/u);
    fields.push(`**${key.trim()}:** ${plainRefs(value)}`);
  }
  const rest = plainRefs(lines.join("\n")).trim();
  return [fields.join("  \n"), rest].filter(Boolean).join("\n\n");
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
function hoverText(text, name) {
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
  const parts = defs.map((d) => `**${d.term}**${d.cond ? ` \`{${d.cond}}\`` : ""}\n\n${definitionMarkdown(definitionBody(lines, d))}`);
  if (comps.length) {
    parts.push(comps.map((c) => "- " + plainRefs(lines[c.line].trim().replace(/^[-*+]\s+/, ""))).join("\n"));
  }
  return parts.join("\n\n---\n\n");
}

module.exports = {
  severity, checkArgs, expand, parseCheckOutput, issueColumns, fold, outline, refAt, findTargets,
  plainRefs, definitionBody, definitionMarkdown, completionContext, completions, hoverText,
};
