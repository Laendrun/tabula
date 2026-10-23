"""What editors show, computed from a file's outline (outline.py): completion, hovers, go to definition,
references, rename, quick fixes, symbols, folding, links, inline hints and use counts. `tabula lsp` (lsp.py)
serves these to VS Code, Neovim and any editor that speaks the Language Server Protocol.

Everything here works with 0-based lines and columns in characters (Python string indices), like the outline;
the server converts them to the editor's units.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from .syntax import fold

SCHEMA_DIR = Path(__file__).with_name("schemas")
BAD_NAME = re.compile(r"[\[\]{}|\n]|^\s*$")
_schemas: dict = {}


def schema(kind: str) -> dict:
    """The JSON Schema of a frontmatter ("game" or "sheet"), shipped with tabula (a copy of spec/schemas)."""
    if kind not in _schemas:
        try:
            _schemas[kind] = json.loads((SCHEMA_DIR / f"{kind}.schema.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            _schemas[kind] = {}
    return _schemas[kind]


def schema_keys(kind: str, level: str) -> list[dict]:
    """The keys of the spec at a level of the frontmatter ("top", or "option": an extension's details)."""
    props = schema(kind).get("properties", {})
    if level == "option":
        opt = ((props.get("extensions", {}).get("oneOf") or [{}, {}])[1].get("additionalProperties") or {})
        props = next((o.get("properties", {}) for o in opt.get("oneOf", []) if o.get("type") == "object"), {})
    elif level != "top":
        return []
    return [{"key": k, "description": v.get("description", "")} for k, v in props.items()]


# ------------------------------------------------------------------ what the outline knows

def all_of(o: dict, kind: str) -> list[dict]:
    """Every definition (or component) a file can refer to: its own, the included fragments', then (a
    translation) the default-language file's. Each with `file` (None: this file)."""
    out = [{**x, "file": None} for x in o[kind]]
    for f in o.get("fragments") or []:
        out += [{**x, "file": f["file"], "from": f["name"]} for x in f[kind]]
    if o.get("default"):
        out += [{**x, "file": o["default"]["file"]} for x in o["default"][kind]]
        for f in o["default"].get("fragments") or []:
            out += [{**x, "file": f["file"], "from": f["name"]} for x in f[kind]]
    return out


def within(x: dict, line: int, col: int) -> bool:
    return x["line"] == line and x["start"] <= col <= x["end"]


def ref_at(o: dict, line: int, col: int) -> dict | None:
    return next((r for r in o["references"] if within(r, line, col)), None)


def include_at(o: dict, line: int) -> dict | None:
    return next((i for i in o["includes"] if i["line"] == line), None)


def section_targets(o: dict, ref: dict) -> list[dict]:
    by_title = [h for h in o["headings"] if h["fold"] == ref["fold"]]
    return by_title or [h for h in o["headings"] if ref["name"].strip().lower() in h["roles"]]


def targets(o: dict, ref: dict) -> list[tuple[str | None, int]]:
    """Where a reference points to: [(file or None for this file, line)], definitions first, then components."""
    if ref["section"]:
        return [(None, h["line"]) for h in section_targets(o, ref)]
    defs = [d for d in all_of(o, "definitions") if d["fold"] == ref["fold"]]
    if defs:
        return [(d["file"], d["line"]) for d in defs]
    return [(c["file"], c["line"]) for c in all_of(o, "components") if c["fold"] == ref["fold"]]


def picture(image: dict | None, images: str) -> str:
    """A card's picture in a hover: an HTML <img> (VS Code), a Markdown image, or its path."""
    if not image:
        return ""
    src = image.get("url") or (Path(image["path"]).as_uri() if image.get("path") and image.get("exists") else None)
    if src and images == "html":
        return f'<img src="{src}" height="160">'
    if src and images == "markdown":
        return f"![]({src})"
    return f"*picture: {image['src']}*"


def definition_hover(d: dict, images: str = "none") -> str:
    head = f"**{d['term']}**" + (f" `{{{d['cond']}}}`" if d["cond"] else "")
    return "\n\n".join(x for x in (head, picture(d.get("image"), images), d["markdown"]) if x)


def reference_hover(o: dict, ref: dict, images: str = "none") -> str | None:
    if ref["section"]:
        hs = section_targets(o, ref)
        if not hs:
            return None
        h = hs[0]
        return (f"**{'★ ' if h['key'] else ''}{h['title']}**" + (f" `{{{h['cond']}}}`" if h["cond"] else "")
                + f"\n\n{h['preview']}").strip()
    parts = [definition_hover(d, images) for d in all_of(o, "definitions") if d["fold"] == ref["fold"]]
    comps = [c for c in o["components"] if c["fold"] == ref["fold"]]
    if comps:
        parts.append("\n".join("- " + c["text"] for c in comps))
    return "\n\n---\n\n".join(parts) if parts else None


def include_hover(inc: dict) -> str:
    if not inc.get("file"):
        return f"No shared fragment `{inc['name']}` (looked for _shared/{inc['name']}.game)"
    where = f" — {inc['section']}" if inc["section"] else ""
    return f"*from `_shared/{inc['name']}`{where}*\n\n{inc.get('preview') or ''}".strip()


def frontmatter_key_hover(kind: str, level: str, key: str) -> str:
    known = next((k for k in schema_keys(kind, level) if k["key"] == key), None)
    if known:
        return f"**{key}**" + (f" — {known['description']}" if known["description"] else "")
    if kind == "sheet":
        return f"**{key}** — not a sheet setting: tabula ignores it."
    label = key.replace("_", " ")
    shown = label[:1].upper() + label[1:] if label == label.lower() else label
    where = " with the extension or variant." if level == "option" else " on the game's page and in `tabula show`."
    return f"**{key}** — your own {'detail' if level == 'option' else 'key'}: shown as “{shown}: …”{where}"


# ------------------------------------------------------------------ the line under the cursor

VALUE_AT = re.compile(r"(?<!\\)\{=\s*([\w-]+)\s*\}")
SYMBOL_AT = re.compile(r"(?<![^\W\d_])(?<![_:\\/]):([A-Za-z][\w+-]*):(?![\w:/])")


def value_at(text: str, col: int) -> tuple[str, int, int] | None:
    for m in VALUE_AT.finditer(text):
        if m.start() <= col <= m.end():
            return m.group(1), m.start(), m.end()
    return None


def symbol_at(text: str, col: int) -> tuple[str, int, int] | None:
    for m in SYMBOL_AT.finditer(text):
        if m.start() <= col <= m.end():
            return m.group(1), m.start(), m.end()
    return None


def hover(o: dict, text: str, line: int, col: int, images: str = "none") -> tuple[str, int, int] | None:
    """(markdown, start, end) for what is under the cursor, or None."""
    fm = o.get("frontmatter")
    if fm:
        k = next((k for k in fm["keys"] if within(k, line, col)), None)
        if k:
            kind = "sheet" if o["kind"] == "sheet" else "game"
            return frontmatter_key_hover(kind, k["level"], k["key"]), k["start"], k["end"]
    inc = include_at(o, line)
    if inc:
        return include_hover(inc), inc["start"], inc["end"]
    if (s := symbol_at(text, col)) and (sym := next((x for x in o["symbols"] if x["name"] == s[0]), None)):
        pic = ""
        if sym.get("image"):
            uri = Path(sym["image"]).as_uri()
            pic = f'<img src="{uri}" height="32">' if images == "html" else f"![{sym['name']}]({uri})" \
                if images == "markdown" else f"*{sym['src']}*"
        shown = pic or (sym.get("text") or "")
        extra = f" — {sym['text']} in the terminal" if sym.get("image") and sym.get("text") else ""
        return f"{shown}  `:{sym['name']}:`{extra}\n\nfrom {sym['from']}", s[1], s[2]
    link = next((l for l in o["links"] if within(l, line, col) and l["kind"] == "image"), None)
    if link:
        if link.get("path") and link.get("exists"):
            uri = Path(link["path"]).as_uri()
            img = f'<img src="{uri}" height="220">' if images == "html" else f"![]({uri})" if images == "markdown" else ""
            body = (img + "\n\n" if img else "") + f"`{link['src']}`"
        elif link.get("url"):
            body = f"![]({link['url']})" if images != "none" else link["url"]
        elif link.get("outside"):
            body = f"`{link['src']}` is outside the vault: tabula doesn't use it"
        else:
            body = f"Image not found: `{link['src']}`"
        return body, link["start"], link["end"]
    if v := value_at(text, col):
        val = next((x for x in o["values"] if x["name"] == v[0]), None)
        body = (f"**{val['name']}** = `{val['value']}`\n\nfrom {val['from']}" if val else
                f"No value `{v[0]}`: define it under `values:` in the frontmatter or in vault.yaml")
        return body, v[1], v[2]
    ref = ref_at(o, line, col)
    if ref and (body := reference_hover(o, ref, images)):
        return body, ref["start"], ref["end"]
    return None


# ------------------------------------------------------------------ completion

def frontmatter_context(o: dict, before: str, line: int) -> dict | None:
    """The frontmatter key being typed: {level, start, present}, or None (not in the frontmatter)."""
    fm = o.get("frontmatter")
    if not fm or not (fm["start"] <= line <= fm["end"]):
        return None
    m = re.match(r"^(\s*)[\w-]*$", before)
    if not m:
        return None
    indent = len(m.group(1))
    if indent == 0:
        return {"level": "top", "start": 0,
                "present": [k["key"] for k in fm["keys"] if k["level"] == "top" and k["line"] != line]}
    opt = next((x for x in reversed(fm["options"]) if x["line"] < line and indent > x["indent"]), None)
    if not opt or any(k["level"] == "top" and opt["line"] < k["line"] <= line for k in fm["keys"]):
        return None
    return {"level": "option", "start": indent,
            "present": [k["key"] for k in fm["keys"] if k.get("option") == opt["name"] and k["line"] != line]}


def item(label, kind, start, end, line, insert=None, detail="", doc="", sort=None, filter_=None) -> dict:
    """A completion item: `range` is where it replaces the typed text (characters on `line`)."""
    out = {"label": label, "kind": kind, "insert": insert if insert is not None else label, "detail": detail,
           "doc": doc, "line": line, "start": start, "end": end}
    if sort is not None:
        out["sort"] = sort
    if filter_ is not None:
        out["filter"] = filter_
    return out


def section_items(headings: list[dict]) -> list[tuple[str, str, str]]:
    out = []
    for h in headings:
        if h["title"]:
            out.append((h["title"], "section", ("★ " if h["key"] else "") + "#" * h["level"]))
            out += [(r, "role", f"→ {h['title']}") for r in h["roles"]]
    return out


def completion(o: dict, text: str, line: int, col: int, file: Path, vault_root: Path, fragment_outline=None) -> list[dict]:
    """The completion items at a position. `fragment_outline(path)` gives the outline of a fragment file
    (for `![[name#` while the include isn't finished)."""
    before, after = text[:col], text[col:]
    closed = re.match(r"^[^\[\]\n]*\]\]", after) is not None
    # ![[name or ![[name#Section
    if m := re.match(r"^\s*!\[\[([^\[\]#|]*)(?:#([^\[\]|]*))?$", before):
        end = "" if closed else "]]"
        if m.group(2) is None:
            shared = vault_root / "_shared"
            names = sorted(p.stem for p in shared.glob("*.game") if "." not in p.stem) if shared.is_dir() else []
            return [item(n, "file", col - len(m.group(1)), col, line, n + end, "shared fragment") for n in names]
        from .fragments import fragment_path
        from .syntax import split_lang
        fp = fragment_path(vault_root, m.group(1).strip(), split_lang(file.stem)[1])
        fo = fragment_outline(fp) if fp and fragment_outline else None
        if not fo:
            return []
        start = col - len(m.group(2))
        return [item(lab, kind, start, col, line, lab + end, f"{kind} in {m.group(1).strip()}", sort=f"{i:05}")
                for i, (lab, kind, _) in enumerate(section_items(fo["headings"]))]
    fm = frontmatter_context(o, before, line)
    if fm is not None:
        kind = "sheet" if o["kind"] == "sheet" else "game"
        what = "extension/variant detail" if fm["level"] == "option" else "sheet setting" if kind == "sheet" else "frontmatter"
        return [item(k["key"], "property", fm["start"], col, line, k["key"] + ": ", what, k["description"])
                for k in schema_keys(kind, fm["level"]) if k["key"] not in fm["present"]]
    if o.get("frontmatter") and o["frontmatter"]["start"] <= line <= o["frontmatter"]["end"]:
        return []
    # :symbol
    if m := re.search(r"(?<![^\W\d_])(?<![_:\\/]):([A-Za-z][\w+-]*)$", before):
        end = col + (1 if after.startswith(":") else 0)
        return [item(f":{s['name']}:", "symbol", m.start(), end, line, f":{s['name']}:",
                     f"symbol from {s['from']}", s.get("text") or s.get("src") or "", filter_=f":{s['name']}")
                for s in o["symbols"]]
    # {=value
    if m := re.search(r"(?<!\\)\{=\s*([\w-]*)$", before):
        end = "" if re.match(r"^[\w-]*\s*\}", after) else "}"
        return [item(v["name"], "constant", col - len(m.group(1)), col, line, v["name"] + end,
                     f"value from {v['from']}", v["value"]) for v in o["values"]]
    # [[term or [[#section
    if m := re.search(r"\[\[(#?)([^\[\]|]*)$", before):
        end = "" if closed else "]]"
        start = col - len(m.group(2))
        out = []
        if m.group(1):
            for i, (lab, kind, detail) in enumerate(section_items(o["headings"])):
                out.append(item(lab, kind, start, col, line, lab + end, detail if kind == "section" else f"role {detail}",
                                sort=f"{i:05}"))
            return out
        seen = set()
        for d in all_of(o, "definitions"):
            if d["fold"] not in seen:
                seen.add(d["fold"])
                out.append(item(d["term"], "definition", start, col, line, d["term"] + end,
                                f"{{{d['cond']}}}" if d["cond"] else ("from " + d["from"] if d.get("from") else "definition"),
                                d["markdown"], sort=f"{len(out):05}"))
        for c in all_of(o, "components"):
            if c["fold"] not in seen:
                seen.add(c["fold"])
                out.append(item(c["name"], "component", start, col, line, c["name"] + end, f"{c['quantity']}x", c["text"],
                                sort=f"{len(out):05}"))
        return out
    return []


# ------------------------------------------------------------------ references, rename

def target_at(o: dict, line: int, col: int) -> dict | None:
    """What rename and "find references" act on: {kind: term|section, fold, name, start, end, missing}."""
    ref = ref_at(o, line, col)
    if ref:
        if ref["section"]:
            h = next((x for x in o["headings"] if x["fold"] == ref["fold"]), None)
            return {"kind": "section", "fold": ref["fold"], "name": h["title"] if h else ref["name"],
                    "start": ref["name_start"], "end": ref["name_end"], "missing": h is None}
        d = next((x for x in o["definitions"] if x["fold"] == ref["fold"]), None)
        return {"kind": "term", "fold": ref["fold"], "name": ref["name"], "placeholder": d["term"] if d else ref["name"],
                "start": ref["name_start"], "end": ref["name_end"]}
    if d := next((x for x in o["definitions"] if x["line"] == line), None):
        return {"kind": "term", "fold": d["fold"], "name": d["term"], "start": d["start"], "end": d["stop"]}
    if (h := next((x for x in o["headings"] if x["line"] == line), None)) and h["title"]:
        return {"kind": "section", "fold": h["fold"], "name": h["title"], "start": h["start"], "end": h["stop"]}
    return None


def occurrences(o: dict, line: int, col: int) -> dict | None:
    """{definitions: [...], references: [...]} for what is at a position (ranges: {line, start, end})."""
    t = target_at(o, line, col)
    if not t:
        return None
    if t["kind"] == "term":
        defs = [{"line": d["line"], "start": d["start"], "end": d["stop"]} for d in o["definitions"] if d["fold"] == t["fold"]]
    else:
        defs = [{"line": h["line"], "start": h["start"], "end": h["stop"]} for h in o["headings"] if h["fold"] == t["fold"]]
    refs = [{"line": r["line"], "start": r["start"], "end": r["end"]} for r in o["references"]
            if r["section"] == (t["kind"] == "section") and r["fold"] == t["fold"]]
    return {"definitions": defs, "references": refs}


class RenameError(Exception):
    pass


def rename_target(o: dict, line: int, col: int) -> dict:
    t = target_at(o, line, col)
    if not t:
        raise RenameError("Put the cursor on a [[reference]], a glossary term or a heading to rename it")
    if t["kind"] == "section" and t.get("missing"):
        raise RenameError("This links to a role or to no heading: nothing to rename")
    return t


def renamed_ref(name: str, alias: str | None, old: str, new: str, prefix: str) -> str:
    """A reference rewritten for a renamed term or section: alias, case and plurals of the old text are kept."""
    if alias is not None:
        return f"[[{prefix}{new}|{alias}]]"
    if name == old:
        return f"[[{prefix}{new}]]"
    if name.lower() == old.lower():                              # "[[bateau]]" for the term "Bateau"
        first = new[0].lower() if name[0] == name[0].lower() else new[0].upper()
        return f"[[{prefix}{first}{new[1:]}]]"
    return f"[[{prefix}{new}|{name}]]"                            # "[[bateaux]]": the text stays as written


def rename_edits(o: dict, line: int, col: int, new: str) -> list[dict]:
    """The edits ({line, start, end, text}) that rename what is at a position, or RenameError."""
    new = new.strip()
    if BAD_NAME.search(new):
        raise RenameError("A name can't be empty or contain [ ] { } or |")
    t = rename_target(o, line, col)
    edits, old = [], t["name"]
    if t["kind"] == "term":
        defs = [d for d in o["definitions"] if d["fold"] == t["fold"]]
        comps = [c for c in o["components"] if c["fold"] == t["fold"]]
        if not defs and not comps:
            raise RenameError(f"'{t['name']}' isn't defined in this file (maybe in a shared fragment): rename it there")
        if defs:
            old = defs[0]["term"]
        edits += [{"line": d["line"], "start": d["start"], "end": d["stop"], "text": new} for d in defs]
    else:
        edits += [{"line": h["line"], "start": h["start"], "end": h["stop"], "text": new}
                  for h in o["headings"] if h["fold"] == t["fold"]]
    prefix = "#" if t["kind"] == "section" else ""
    for r in o["references"]:
        if r["section"] == (t["kind"] == "section") and r["fold"] == t["fold"]:
            edits.append({"line": r["line"], "start": r["start"], "end": r["end"],
                          "text": renamed_ref(r["name"], r["alias"], old, new, prefix)})
    return edits


# ------------------------------------------------------------------ outline view, use counts

def use_counts(o: dict) -> list[dict]:
    """Definitions (always) and headings that are linked to: {line, kind, name, count, refs}."""
    terms: dict = {}
    sections: dict = {}
    for r in o["references"]:
        (sections if r["section"] else terms).setdefault(r["fold"], []).append(r)
    out = [{"line": d["line"], "kind": "term", "name": d["term"], "refs": terms.get(d["fold"], [])} for d in o["definitions"]]
    out += [{"line": h["line"], "kind": "section", "name": h["title"], "refs": sections[h["fold"]]}
            for h in o["headings"] if h["title"] and h["fold"] in sections]
    for u in out:
        u["count"] = len(u["refs"])
    return sorted(out, key=lambda u: u["line"])


def symbols(o: dict) -> list[dict]:
    """The outline as nested symbols: {name, detail, kind: section|term|component, line, end, children}."""
    root: list = []
    stack: list = []
    for h in o["headings"]:
        attrs = " ".join(x for x in [h["cond"], *("#" + r for r in h["roles"])] if x)
        s = {"name": ("★ " if h["key"] else "") + (h["title"] or "(untitled)"), "detail": f"{{{attrs}}}" if attrs else "",
             "kind": "section", "line": h["line"], "end": h["end"], "children": []}
        while stack and stack[-1][0] >= h["level"]:
            stack.pop()
        (stack[-1][1]["children"] if stack else root).append(s)
        stack.append((h["level"], s))

    def parent(line: int) -> list:
        best = root
        level = root
        while True:
            hit = next((s for s in level if s["line"] <= line <= s["end"]), None)
            if not hit:
                return best
            best = level = hit["children"]

    for d in o["definitions"]:
        parent(d["line"]).append({"name": d["term"], "detail": f"{{{d['cond']}}}" if d["cond"] else "", "kind": "term",
                                  "line": d["line"], "end": d["end"], "children": []})
    for c in o["components"]:
        parent(c["line"]).append({"name": c["name"], "detail": f"{c['quantity']}x", "kind": "component",
                                  "line": c["line"], "end": c["line"], "children": []})

    def sort(lst):
        lst.sort(key=lambda s: s["line"])
        for s in lst:
            sort(s["children"])
    sort(root)
    return root


def folding(o: dict) -> list[tuple[int, int]]:
    return [(x["line"], x["end"]) for x in o["headings"] + o["definitions"] if x["end"] > x["line"]]


# ------------------------------------------------------------------ squiggles and quick fixes

def issue_columns(text: str, message: str) -> tuple[int, int]:
    """Where to underline a problem on its line: the first thing the message quotes that is on it."""
    cands = []
    for rx in (r"^unknown word '(.+?)'(?= \(|$)", r"\[\[[^\]]*\]\]?", r"\{[^{}]*\}", r"'([^']+)'", r'"([^"]+)"', r"‘([^’]+)’"):
        for m in re.finditer(rx, message):
            cands.append(m.group(1) if m.groups() else m.group(0))
    for c in cands:
        if not c.strip():
            continue
        if re.fullmatch(r"[^\W\d_']+(?:'[^\W\d_]+)*", c):          # a word: the whole word, not part of a longer one
            if w := re.search(rf"(?<![\w']){re.escape(c)}(?!\w)", text):
                return w.start(), w.start() + len(c)
        at = text.find(c)
        if at < 0:
            at = text.lower().find(c.lower())
        if at >= 0:
            return at, at + len(c)
    first = len(text) - len(text.lstrip())
    return (first, len(text.rstrip())) if text.strip() else (0, len(text))


def distance(a: str, b: str) -> int:
    row = list(range(len(b) + 1))
    for i in range(1, len(a) + 1):
        prev, row[0] = row[0], i
        for j in range(1, len(b) + 1):
            cur = row[j]
            row[j] = min(row[j] + 1, row[j - 1] + 1, prev + (a[i - 1] != b[j - 1]))
            prev = cur
    return row[len(b)]


def closest(name: str, names: list[str]) -> list[str]:
    key, seen, scored = fold(name), set(), []
    for n in names:
        if fold(n) in seen:
            continue
        seen.add(fold(n))
        d = distance(key, fold(n))
        if 0 < d <= max(2, len(key) // 3):
            scored.append((d, n))
    return [n for _, n in sorted(scored, key=lambda x: x[0])[:3]]


def quick_fixes(lines: list[str], o: dict, line: int, message: str, start: int, end: int) -> list[dict]:
    """Fixes for one of tabula's problems: [{title, edits: [{line, start, end, text}], preferred, add_word}]."""
    lt = lines[line] if line < len(lines) else ""
    out: list[dict] = []
    if m := re.match(r"^unknown word '(.+?)'(?: \(did you mean '(.+?)'\?\))?$", message):
        word = m.group(1)
        if m.group(2):
            fix = m.group(2)[0].upper() + m.group(2)[1:] if word[0] == word[0].upper() else m.group(2)
            out.append({"title": f"Change to '{fix}'", "edits": [{"line": line, "start": start, "end": end, "text": fix}],
                        "preferred": True})
        plain = word.split("'")[-1] if "'" in word else word
        out.append({"title": f"Add '{plain}' to words.txt", "edits": [], "add_word": plain})
    elif m := re.match(r"^'(.+?):' in frontmatter: did you mean '(.+?)'\?", message):
        k = next((i for i, l in enumerate(lines[1:200], 1) if l.startswith(m.group(1) + ":")), None)
        if k:
            out.append({"title": f"Change to '{m.group(2)}:'", "preferred": True,
                        "edits": [{"line": k, "start": 0, "end": len(m.group(1)), "text": m.group(2)}]})
    elif m := re.match(r"^role '#(.+?)': did you mean '#(.+?)'\?", message):
        if r := re.search(rf"#{re.escape(m.group(1))}(?![\w-])", lt):
            out.append({"title": f"Change to '#{m.group(2)}'", "preferred": True,
                        "edits": [{"line": line, "start": r.start() + 1, "end": r.end(), "text": m.group(2)}]})
    elif m := re.match(r"^'\[(.+?)\]' has single brackets", message):
        at = lt.find(f"[{m.group(1)}]")
        if at >= 0:
            out.append({"title": f"Change to [[{m.group(1)}]]", "preferred": True,
                        "edits": [{"line": line, "start": at, "end": at + len(m.group(1)) + 2, "text": f"[[{m.group(1)}]]"}]})
    elif m := re.match(r"^(\[\[(#?)([^\]|]+?)(?:\|([^\]]*))?\]\]) matches no", message):
        raw, hash_, name, alias = m.groups()
        at = lt.find(raw)
        if at < 0:
            return out
        pool = ([h["title"] for h in o["headings"] if h["title"]] if hash_ else
                [d["term"] for d in all_of(o, "definitions")] + [c["name"] for c in all_of(o, "components")])
        for c in closest(name.strip(), pool):
            text = f"[[{hash_}{c}{'|' + alias if alias is not None else ''}]]"
            out.append({"title": f"Change to [[{hash_}{c}]]", "edits": [{"line": line, "start": at, "end": at + len(raw), "text": text}]})
        if len(out) == 1:
            out[0]["preferred"] = True
        g = -1 if hash_ else o.get("glossary_line", -1)
        if g >= 0:
            term = name.strip()[0].upper() + name.strip()[1:]
            before = "\n" if g > 0 and g <= len(lines) and lines[g - 1].strip() else ""
            out.append({"title": f"Define '{term}' in the glossary",
                        "edits": [{"line": g, "start": 0, "end": 0, "text": f"{before}{term}\n: \n\n"}]})
    return out


def add_word(vault_root: Path, word: str) -> Path:
    """Add a word to the vault's words.txt (created if needed); returns the file."""
    f = vault_root / "words.txt"
    text = f.read_text(encoding="utf-8") if f.is_file() else "# Words the spell check accepts (tabula check --spell), one per line\n"
    words = {l.split("#")[0].strip().lower() for l in text.splitlines()}
    if word.lower() not in words:
        if text and not text.endswith("\n"):
            text += "\n"
        f.write_text(text + word + "\n", encoding="utf-8")
    return f
