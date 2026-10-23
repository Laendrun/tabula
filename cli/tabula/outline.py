"""`tabula outline FILE --json`: what a file contains, for editors (VS Code, Neovim…), so they don't parse the
format themselves: headings, definitions (with their fields, totals and a hover text), components, every
[[reference]] and ![[include]] with its columns, values, symbols, inline hints, clickable paths, TODOs, the
terms of the included fragments and, for a translation, of the default-language file.

Positions are 0-based: `line` is the line's index in the file, and columns count characters (code points)
from the start of the line. `end` is the last line of a section or a definition (included). `fold` is the
key references are matched by (case, accents and plurals ignored): compare those, never the names.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

from .blocks import Block, components_of, parse_blocks
from .fragments import INCLUDE_RE, SHARED_DIR, fragment_path, select_section
from .source import UNSAVED, local_file, raw_text, read_source, strip_comments, Issues
from .symbols import symbol_parts
from .syntax import FENCE_RE, FIELD_RE, IMAGE_RE, REF_RE, fold, split_lang
from .totals import definitions as total_defs, members, number, parts, total
from .values import VALUE_RE

OUTLINE_VERSION = 1
GLOSSARY_TITLES = ("glossary", "glossaire", "glossar", "glosario", "glossario")


def plain_refs(text: str) -> str:
    """'[[a|b]]' -> 'b', '[[#Sec]]' -> 'Sec' (for hover texts)."""
    return re.sub(r"\[\[#?([^\]|]+)(?:\|([^\]]*))?\]\]", lambda m: (m.group(2) or m.group(1)).strip(), text)


class Source:
    """A file's lines, and which of them are text (not frontmatter, comment or code)."""

    def __init__(self, path: Path):
        self.path = path
        text = raw_text(path).lstrip("﻿").replace("\r\n", "\n").replace("\r", "\n")
        self.lines = text.split("\n")
        self.fm = None                                     # (first, last) line of the frontmatter body
        if self.lines and self.lines[0].strip() == "---":
            end = next((k for k in range(1, len(self.lines)) if self.lines[k].strip() in ("---", "...")), None)
            if end is not None:
                self.fm = (1, end - 1)
        stripped, _, _ = strip_comments(text.replace("\x00", ""))
        self.clean = stripped.split("\n")                 # comments blanked out
        self.text_line = [True] * len(self.lines)
        if self.fm:
            for k in range(0, self.fm[1] + 2):
                self.text_line[k] = False
        fence = None
        for k, t in enumerate(self.clean):
            if fence:
                self.text_line[k] = False
                if t.strip().startswith(fence):
                    fence = None
            elif m := FENCE_RE.match(t):
                fence, self.text_line[k] = m.group(1), False

    def masked(self, k: int) -> str:
        """A text line with `inline code` blanked out (columns kept), or '' for other lines."""
        if not self.text_line[k]:
            return ""
        return re.sub(r"`[^`\n]*`", lambda m: " " * len(m.group(0)), self.clean[k])


def last_line(b: Block) -> int:
    """The last (1-based) line a block covers."""
    n = b.line
    for ln, _ in b.src or []:
        n = max(n, ln)
    for ln, _ in b.rows or []:
        n = max(n, ln)
    for v in (b.field_lines or {}).values():
        if isinstance(v, int):
            n = max(n, v)
    for it in b.items or []:
        if len(it) > 2 and isinstance(it[2], int):
            n = max(n, it[2])
    for c in b.children or []:
        n = max(n, last_line(c))
    return n


def heading_ends(blocks: list[Block], nlines: int, src: Source) -> dict[int, int]:
    """id(heading) -> its section's last line (0-based, trailing blank lines left out)."""
    heads = [b for b in blocks if b.kind == "heading"]
    out = {}
    for i, h in enumerate(heads):
        if h.reopens or h.hidden:
            continue
        end = nlines - 1
        depth = []
        for later in heads[i + 1:]:
            if later.reopens:                 # "---": closes the innermost open section
                if not depth:
                    end = later.line - 1      # 1-based line of "---" -> its 0-based index; the section ends on it
                    break
                depth.pop()
            elif later.level <= h.level:
                end = later.line - 2
                break
            else:
                while depth and depth[-1] >= later.level:
                    depth.pop()
                depth.append(later.level)
        while end > h.line - 1 and not src.lines[end].strip():
            end -= 1
        out[id(h)] = end
    return out


def find_col(line: str, text: str, after: int = 0) -> int:
    i = line.find(text, after)
    return i if i >= 0 else max(0, len(line) - len(line.lstrip()))


def definition_body(src: Source, d: Block, end: int) -> list[str]:
    """The lines of a definition after its fields: ': ' markers and the common indentation removed."""
    skip = max([d.line] + [v for v in (d.field_lines or {}).values() if isinstance(v, int)])   # 1-based
    body = []
    for k in range(d.line, end + 1):                       # 0-based d.line .. end = the lines after the term
        if k + 1 <= skip:
            # a field line (or the term): the text after the fields may start on the ':' line itself
            continue
        body.append(re.sub(r"^ {0,3}:(\s|$)", "  ", src.lines[k]))
    # continuation lines of the last field are indented deeper: drop them
    last_field = [k for k, v in (d.field_lines or {}).items() if isinstance(v, int)]
    if last_field:
        while body and re.match(r"^\s{3,}\S", body[0]):
            body.pop(0)
    ind = min((len(x) - len(x.lstrip()) for x in body if x.strip()), default=0)
    out = [x[ind:] if x.strip() else "" for x in body]
    while out and not out[0].strip():
        out.pop(0)
    while out and not out[-1].strip():
        out.pop()
    return out


def image_info(base: Path, src: str, root: Path | None) -> dict:
    """{path (absolute, when it's a file of the vault), url, exists} for a picture path."""
    if re.match(r"^https?://", src, re.I):
        return {"url": src}
    f = local_file(base, src, root)
    return {"path": str(f.resolve()), "exists": f.is_file()} if f is not None else {"outside": True}


def needed(conds) -> list[str]:
    """The extensions and variants the conditions turn on (each once)."""
    out = []
    for c in conds:
        for k, neg, v in (c.tokens if c else []):
            if k == "v" and not neg and v not in out:
                out.append(v)
    return out


def outline_file(path: Path, vault, depth: int = 0) -> dict:
    """The outline of one .game (or .sheet) file, as a dict (see the module's docstring)."""
    path = Path(path)
    src = Source(path)
    issues = Issues()
    meta, lines = read_source(path, issues)
    blocks = parse_blocks(lines)
    base = path.parent
    root = vault.root
    nlines = len(src.lines)
    is_sheet = path.suffix == ".sheet"
    slug, lang = split_lang(path.stem)
    is_fragment = path.parent.name == SHARED_DIR
    out: dict = {"outline": OUTLINE_VERSION, "file": str(path.resolve()), "vault": str(root),
                 "kind": "sheet" if is_sheet else "fragment" if is_fragment else "game",
                 "language": lang or str(meta.get("language") or vault.language)}

    # ---- frontmatter: keys, and the extensions/variants whose details are indented under them
    fm = None
    if src.fm:
        first, last = src.fm
        keys, options, parent, option = [], [], None, None
        for k in range(first, last + 1):
            t = src.lines[k]
            m = re.match(r"^(\s*)([\w-]+)\s*:", t)
            if not t.strip() or t.lstrip().startswith("#"):
                continue
            ind = len(t) - len(t.lstrip())
            if ind == 0:
                parent, option = (m.group(2) if m else None), None
                if m:
                    keys.append({"key": m.group(2), "line": k, "start": 0, "end": len(m.group(2)), "level": "top"})
            elif m and parent in ("extensions", "variants") and (option is None or ind <= option["indent"]):
                option = {"name": m.group(2), "line": k, "end": k, "indent": ind, "kind": parent}
                options.append(option)
            elif option and ind > option["indent"]:
                option["end"] = k
                if m:
                    keys.append({"key": m.group(2), "line": k, "start": ind, "end": ind + len(m.group(2)),
                                 "level": "option", "option": option["name"]})
        fm = {"start": first, "end": last, "keys": keys,
              "options": options}
    out["frontmatter"] = fm

    # ---- headings
    ends = heading_ends(blocks, nlines, src)
    headings = []
    for b in blocks:
        if b.kind != "heading" or b.reopens or b.hidden:
            continue
        raw = src.lines[b.line - 1]
        start = find_col(raw, b.text, len(raw) - len(raw.lstrip("#")) if b.text else 0)
        body = [plain_refs(x) for x in src.lines[b.line: min(ends[id(b)], b.line + 11) + 1]]
        title = plain_refs(b.text)              # "Déplacer le [[Pion]]" is the section "Déplacer le Pion"
        headings.append({"level": b.level, "title": title, "fold": fold(title), "roles": b.roles, "cond": b.cond.raw if b.cond else "",
                         "key": b.key, "line": b.line - 1, "end": ends[id(b)], "start": start,
                         "stop": start + len(b.text), "preview": "\n".join(body).strip()})
    out["headings"] = headings

    # ---- definitions, with their fields, totals and hover text
    tdefs = total_defs(blocks)
    definitions = []
    for b in blocks:
        if b.kind != "def":
            continue
        end = last_line(b) - 1
        raw = src.lines[b.line - 1]
        start = find_col(raw, b.term)
        fields, image, md_fields = [], None, []
        is_group = bool(members(b))
        for key, value in (b.fields or {}).items():
            ln = (b.field_lines or {}).get(key, b.line + 1)
            f = {"key": key, "value": value, "line": ln - 1}
            if value == "" and is_group:
                ps = parts(b, key, tdefs, frozenset({fold(b.term)}))
                if ps:
                    every = total([x for _, x in ps])
                    basic = total([x for conds, x in ps if not needed(conds)])
                    f["total"] = {"all": every, "base": basic,
                                  "parts": [{"value": x, "needs": needed(conds)} for conds, x in ps]}
                    label = every if basic in ("", every) else f"{every} (base game: {basic})"
                    md_fields.append(f"**{key}:** Σ {label}")
            elif key == "image":
                image = {"src": value, **image_info(base, value, root)}
            else:
                md_fields.append(f"**{key}:** {plain_refs(value)}")
            fields.append(f)
        body = definition_body(src, b, end)
        md = "\n\n".join(x for x in ["  \n".join(md_fields), plain_refs("\n".join(body)).strip()] if x)
        definitions.append({"term": b.term, "fold": fold(b.term), "cond": b.cond.raw if b.cond else "", "line": b.line - 1, "end": end,
                            "start": start, "stop": start + len(b.term), "fields": fields, "image": image,
                            "markdown": md})
    out["definitions"] = definitions

    # the cards a total adds up, by name (for the tooltip of the inline hint)
    for d in definitions:
        block = next(b for b in blocks if b.kind == "def" and b.line - 1 == d["line"])
        for f in d["fields"]:
            if "total" in f:
                names = []
                for conds, target in members(block):
                    if target in tdefs and f["key"] in tdefs[target][0].fields:
                        names.append(tdefs[target][0].term)
                for p, n in zip(f["total"]["parts"], names):
                    p["card"] = n

    # ---- components
    comps = []
    for c in components_of(blocks):
        comps.append({"name": c["name"], "fold": fold(c["name"]), "quantity": c["quantity"], "line": c["line"] - 1, "cond": c.get("cond", ""),
                      "parent": c.get("part_of"), "text": plain_refs(src.lines[c["line"] - 1].strip().lstrip("-*+ "))})
    out["components"] = comps

    # ---- references, includes, values, images: everything with columns
    refs, includes, links, value_uses = [], [], [], []
    for k in range(nlines):
        t = src.masked(k)
        if not t:
            continue
        if m := INCLUDE_RE.match(t):
            name, section = m.group(2).strip(), (m.group(3) or "").strip()
            fp = fragment_path(root, name, lang)
            includes.append({"name": name, "section": section, "line": k, "start": m.start(2), "end": m.end(2),
                             "file": str(fp.resolve()) if fp else None})
            if fp:
                links.append({"line": k, "start": m.start(2), "end": m.end(2), "file": str(fp.resolve()),
                              "kind": "fragment", "exists": True})
            continue
        for m in REF_RE.finditer(t):
            if m.start() > 0 and t[m.start() - 1] == "!":
                continue
            name = m.group(1).strip()
            section = name.startswith("#")
            refs.append({"name": name[1:].strip() if section else name, "fold": fold(name[1:] if section else name),
                         "alias": (m.group(2) or "").strip() or None,
                         "section": section, "line": k, "start": m.start(), "end": m.end(),
                         "name_start": m.start(1) + (len(m.group(1)) - len(m.group(1).lstrip())) + (1 if section else 0),
                         "name_end": m.end(1) - (len(m.group(1)) - len(m.group(1).rstrip()))})
        for m in IMAGE_RE.finditer(t):
            if m.group(1).startswith("sym:"):
                continue
            info = image_info(base, m.group(2), root)
            links.append({"line": k, "start": m.start(2), "end": m.end(2), "kind": "image", "src": m.group(2), **info})
        if (fm_ := re.match(r"^(\s*(?::\s*)?image::\s*)(\S+)", t)):
            info = image_info(base, fm_.group(2), root)
            links.append({"line": k, "start": fm_.end(1), "end": fm_.end(2), "kind": "image", "src": fm_.group(2),
                          **info})
        for m in VALUE_RE.finditer(t):
            value_uses.append((k, m))
    if src.fm and isinstance(meta.get("cover"), str) and meta["cover"].strip():
        for k in range(src.fm[0], src.fm[1] + 1):
            if (cm := re.match(r"^(cover:\s*)(\S+)", src.lines[k])):
                links.append({"line": k, "start": cm.end(1), "end": cm.end(2), "kind": "image", "src": cm.group(2),
                              **image_info(base, cm.group(2), root)})
    out["references"], out["includes"], out["links"] = refs, includes, links

    # ---- values and symbols: the file's, the default-language file's (a translation), vault.yaml's
    default_file = base / f"{slug}.game" if lang and not is_sheet else None
    default_meta = {}
    if default_file and default_file.is_file() and default_file != path:
        default_meta, _ = read_source(default_file, Issues())
    else:
        default_file = None
    sources = [(meta, "this file", base), (default_meta, "the default-language file", base),
               (vault.config, "vault.yaml", root)]
    values, symbols, seen_v, seen_s = [], [], set(), set()
    for m_, origin, folder in sources:
        vals = (m_ or {}).get("values")
        if isinstance(vals, dict):
            for name, v in vals.items():
                if str(name) not in seen_v:
                    seen_v.add(str(name))
                    values.append({"name": str(name), "value": value_label(v), "from": origin})
        syms = (m_ or {}).get("symbols")
        if isinstance(syms, dict):
            for name, v in syms.items():
                if str(name) in seen_s:
                    continue
                seen_s.add(str(name))
                img, text = symbol_parts(v)
                f = local_file(folder, img, root) if img else None
                symbols.append({"name": str(name), "text": text, "image": str(f.resolve()) if f else None,
                                "src": img, "from": origin})
    out["values"], out["symbols"] = values, symbols

    # ---- inline hints: what {=value} stands for, parts that don't add up, totals
    hints = []
    by_name = {v["name"]: v for v in values}
    for k, m in value_uses:
        if (v := by_name.get(m.group(1))):
            hints.append({"line": k, "character": m.end(), "label": f"= {v['value']}", "tooltip": f"from {v['from']}"})
    kids: dict[int, list] = {}
    for c in components_of(blocks):
        if c.get("part_of"):
            parent = next((p for p in reversed(components_of(blocks)) if p["name"] == c["part_of"]
                           and p["line"] < c["line"]), None)
            if parent:
                kids.setdefault(parent["line"], []).append(c)
    for c in components_of(blocks):
        parts_ = kids.get(c["line"], [])
        if len(parts_) > 1 and c["quantity"].isdigit() and all(p["quantity"].isdigit() for p in parts_):
            s = sum(int(p["quantity"]) for p in parts_)
            if s != int(c["quantity"]):
                k = c["line"] - 1
                hints.append({"line": k, "character": len(src.lines[k]), "label": f"parts: {s} ≠ {c['quantity']}",
                              "tooltip": "the indented parts don't add up to this count"})
    for d in definitions:
        for f in d["fields"]:
            if "total" in f:
                tt = f["total"]
                label = tt["all"] if tt["base"] in ("", tt["all"]) else f"{tt['all']} (base game: {tt['base']})"
                detail = "\n".join(f"{p.get('card', '')}: {p['value']}" + (f" (+{' +'.join(p['needs'])})"
                                                                         if p["needs"] else "") for p in tt["parts"])
                hints.append({"line": f["line"], "character": len(src.lines[f["line"]]), "label": f"Σ {label}",
                              "tooltip": detail})
    out["hints"] = sorted(hints, key=lambda h: (h["line"], h["character"]))

    # ---- TODOs, and where a new glossary term goes
    out["todos"] = [{"line": k, "text": " ".join(m.group(1).split()) or "TODO"}
                    for k, t in enumerate(src.lines)
                    for m in re.finditer(r"<!--\s*(?:TODO|FIXME)\b:?\s*(.*?)\s*-->", t)]
    g = next((h for h in headings if "glossary" in h["roles"]), None) or \
        next((h for h in headings if h["title"].strip().lower() in GLOSSARY_TITLES), None)
    if g is None:
        out["glossary_line"] = -1
    else:
        sub = next((h for h in headings if g["line"] < h["line"] <= g["end"] and h["level"] > g["level"]), None)
        out["glossary_line"] = sub["line"] if sub else g["end"] + 1

    # ---- the included fragments' and the default-language file's terms (their own files and lines)
    out["fragments"] = []
    if depth < 3:
        done = set()
        for inc in includes:
            if inc["file"] and inc["file"] not in done:
                done.add(inc["file"])
                sub = outline_file(Path(inc["file"]), vault, depth + 1)
                out["fragments"].append({"name": inc["name"], **{k: sub[k] for k in
                                         ("file", "headings", "definitions", "components")}})
            if inc["file"]:
                inc["preview"] = include_preview(Path(inc["file"]), inc["section"])
                frag = next(f for f in out["fragments"] if f["file"] == inc["file"])
                want = inc["section"].strip()
                h = (next((h for h in frag["headings"] if h["fold"] == fold(want)), None)
                     or next((h for h in frag["headings"] if want.lower() in h["roles"]), None)) if want else None
                inc["section_line"] = h["line"] if h else 0
    out["default"] = None
    if default_file and depth < 3:
        sub = outline_file(default_file, vault, depth + 1)
        out["default"] = {k: sub[k] for k in ("file", "headings", "definitions", "components", "fragments")}
    return out


def value_label(v) -> str:
    """{2p: 7, "*": 5} -> '2p 7 · * 5'; a plain value as it is."""
    if isinstance(v, dict):
        return " · ".join(f"{k} {'' if x is None else x}".strip() for k, x in v.items())
    if isinstance(v, bool):
        return "yes" if v else "no"
    return "" if v is None else str(v)


def include_preview(fp: Path, section: str, limit: int = 14) -> str:
    """What `![[name#section]]` includes, as a short text for a hover."""
    try:
        texts = Source(fp).lines
    except OSError:
        return ""
    meta_end = 0
    if texts and texts[0].strip() == "---":
        meta_end = next((k + 1 for k in range(1, len(texts)) if texts[k].strip() in ("---", "...")), 0)
    texts = texts[meta_end:]
    if section:
        picked = select_section(texts, section)
        if picked is None:
            return f"No section '{section}' in {fp.name}"
        texts = picked[0]
    texts = [plain_refs(t) for t in texts]
    while texts and not texts[0].strip():
        texts.pop(0)
    more = "\n\n…" if len(texts) > limit else ""
    return "\n".join(texts[:limit]).rstrip() + more


def cmd_outline(args) -> int:
    from .vault import open_vault
    path = Path(args.file)
    if args.stdin:
        UNSAVED[path.resolve()] = sys.stdin.buffer.read().decode("utf-8", errors="replace")
    elif not path.is_file():
        print(f"tabula: no file {path}", file=sys.stderr)
        return 2
    vault = open_vault(args.vault, str(path))
    data = outline_file(path, vault)
    if args.json:
        sys.stdout.buffer.write(json.dumps(data, ensure_ascii=False).encode("utf-8") + b"\n")
        return 0
    # a readable outline: headings with their terms and components
    for h in data["headings"]:
        print(f"{'  ' * (h['level'] - 1)}{'★ ' if h['key'] else ''}{h['title']}"
              + (f"  {{{h['cond']}}}" if h["cond"] else "") + "".join(f" #{r}" for r in h["roles"])
              + f"  (line {h['line'] + 1})")
    if data["definitions"]:
        print(f"\n{len(data['definitions'])} definition(s): " + ", ".join(d["term"] for d in data["definitions"]))
    if data["components"]:
        print(f"{len(data['components'])} component(s): " + ", ".join(c["name"] for c in data["components"]))
    print(f"{len(data['references'])} reference(s), {len(data['includes'])} include(s)")
    return 0
