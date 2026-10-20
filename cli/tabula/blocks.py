"""Parsing a game body into blocks: headings, paragraphs, lists, tables, definitions…"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from .syntax import (
    BLOCK_COND_RE, COMPONENT_RE, Cond, DEF_LINE_RE, END_RE, FENCE_RE, FIELD_RE, HEADING_COND_RE,
    HEADING_RE, IMAGE_RE, ITEM_RE, P_TOKEN, REF_RE, parse_attrs, parse_cond, parse_range,
)

QUIET_END = "---\x00quiet"     # see fragments.expand_includes


@dataclass
class Block:
    kind: str                 # heading para item note key table image def code
    text: str = ""
    line: int = 0
    level: int = 0            # heading level / item indent
    ordered: bool = False
    key: bool = False         # list item marked "!"
    cond: Cond | None = None
    rows: list = field(default_factory=list)    # table: [(line, [cells])]
    term: str = ""            # def: term / image: src
    items: list = field(default_factory=list)   # def: [[kind('p'|'li'), text, line]]
    qty: str = ""             # component declaration
    src: list = field(default_factory=list)     # [(line, raw text)] for exact error positions
    children: list = field(default_factory=list)  # def: the definition body, parsed as blocks
    start: int = 1            # ordered item: its number (a list continues from its first number)
    parent: str = ""          # component nested under another component
    fields: dict = field(default_factory=dict)  # def: card fields written as "key:: value"
    field_lines: dict = field(default_factory=dict)  # def: key -> line number (for check)
    via: tuple = ()           # filtered view: the enabled extensions/variants this block comes from
    roles: list = field(default_factory=list)   # heading: section roles like "glossary", "components"
    tint: bool = False        # filtered view: nested under a block that comes from an extension
    reopens: int = 0          # heading made by "---": back in the section whose heading is on this line
    quiet: bool = False       # an end added after an included fragment: closes its sections, shows nothing


def is_block_start(t: str) -> bool:
    s = t.lstrip()
    return (not s or bool(HEADING_RE.match(t)) or bool(END_RE.match(t)) or s.startswith("|") or bool(ITEM_RE.match(t))
            or s.startswith(">") or (t.startswith("!") and not t.startswith("![")) or bool(FENCE_RE.match(t))
            or bool(DEF_LINE_RE.match(t)) or bool(BLOCK_COND_RE.match(t)))


def split_row(t: str) -> list[str]:
    s = t.strip()
    s = s[1:] if s.startswith("|") else s
    s = s[:-1] if s.endswith("|") else s
    return [c.strip() for c in s.split("|")]


def is_sep_row(cells) -> bool:
    return any(cells) and all(re.fullmatch(r":?-{3,}:?|:?-+:?", c) for c in cells if c)


def parse_blocks(lines: list[tuple[int, str]]) -> list[Block]:
    blocks: list[Block] = []
    heads: list[Block] = []          # open sections, outermost first
    i, n = 0, len(lines)
    while i < n:
        ln, t = lines[i]
        if not t.strip():
            i += 1
            continue
        if END_RE.match(t) or t == QUIET_END:
            # "---" ends the innermost section: what follows belongs to the section around it again.
            # It becomes an invisible heading that reopens that section (or no section at all).
            if heads:
                heads.pop()
            up = heads[-1] if heads else None
            blocks.append(Block("heading", up.text if up else "", ln, level=up.level if up else 0,
                                cond=up.cond if up else None, roles=list(up.roles) if up else [],
                                reopens=(up.reopens or up.line) if up else -1, quiet=t == QUIET_END))
            i += 1
            continue
        if FENCE_RE.match(t):
            fence = FENCE_RE.match(t).group(1)
            body = []
            i += 1
            while i < n and not lines[i][1].strip().startswith(fence):
                body.append(lines[i][1])
                i += 1
            i += 1
            blocks.append(Block("code", "\n".join(body), ln))
            continue
        if m := HEADING_RE.match(t):
            title, cond, roles = m.group(2), None, []
            key = title.startswith("!") and not title.startswith("![")       # "## ! Title": a key section
            if key:
                title = title[1:].lstrip()
            if (cm := HEADING_COND_RE.search(title)) and (attrs := parse_attrs(cm.group(1))):
                (cond, roles), title = attrs, title[: cm.start()]
            blocks.append(Block("heading", title.strip(), ln, level=len(m.group(1)), cond=cond, roles=roles,
                                key=key))
            while heads and heads[-1].level >= blocks[-1].level:
                heads.pop()
            heads.append(blocks[-1])
            i += 1
            continue
        if t.lstrip().startswith("|"):
            rows = []
            while i < n and lines[i][1].lstrip().startswith("|"):
                rows.append((lines[i][0], split_row(lines[i][1])))
                i += 1
            blocks.append(Block("table", line=ln, rows=rows, level=len(t) - len(t.lstrip())))
            continue
        if m := ITEM_RE.match(t):
            indent, text = len(m.group(1)), m.group(3)
            src = [(ln, m.group(3))]
            i += 1
            while i < n:
                nt = lines[i][1]
                if (not nt.strip() or ITEM_RE.match(nt) or len(nt) - len(nt.lstrip()) <= indent
                        or nt.lstrip().startswith((">", "|"))):
                    break
                text += " " + nt.strip()
                src.append((lines[i][0], nt.strip()))
                i += 1
            marker = m.group(2)
            blocks.append(Block("item", text, ln, level=indent, ordered=marker not in "-*+", src=src,
                                start=int(marker[:-1]) if marker not in "-*+" else 1))
            continue
        if t.lstrip().startswith(">"):
            parts, src = [], []
            level = len(t) - len(t.lstrip())
            while i < n and lines[i][1].lstrip().startswith(">"):
                parts.append(lines[i][1].lstrip()[1:].strip())
                src.append((lines[i][0], parts[-1]))
                i += 1
            blocks.append(Block("note", " ".join(parts), ln, src=src, level=level))
            continue
        if im := IMAGE_RE.fullmatch(t.strip()):
            blocks.append(Block("image", im.group(1), ln, term=im.group(2)))
            i += 1
            continue
        # definition: a term line followed by ": definition"
        pre = BLOCK_COND_RE.match(t.strip())
        pre_cond = parse_cond(pre.group(1)) if pre else None
        term_text = t.strip()[pre.end():] if pre_cond else t
        if i + 1 < n and DEF_LINE_RE.match(lines[i + 1][1]) and term_text.strip() and not is_block_start(term_text):
            term, cond, i = term_text.strip(), pre_cond, i + 1      # condition before the term…
            if cond is None and (cm := HEADING_COND_RE.search(term)) and (c := parse_cond(cm.group(1))):
                cond, term = c, term[: cm.start()].strip()           # …or after it
            body: list[tuple[int, str]] = []
            while i < n:
                lln, lt = lines[i]
                if m := DEF_LINE_RE.match(lt):
                    if body:
                        body.append((lln, ""))          # a new ": " starts a new paragraph
                    if m.group(1):
                        body.append((lln, "  " + m.group(1)))
                elif lt.startswith(" ") and lt.strip():
                    body.append((lln, lt))
                elif not lt.strip() and i + 1 < n and (DEF_LINE_RE.match(lines[i + 1][1])
                                                       or (lines[i + 1][1].startswith(" ") and lines[i + 1][1].strip())):
                    body.append((lln, ""))
                else:
                    break
                i += 1
            ind = min((len(x) - len(x.lstrip()) for _, x in body if x.strip()), default=0)
            body = [(l, x[ind:] if x.strip() else "") for l, x in body]
            fields, field_lines = {}, {}          # "key:: value" lines at the top of the definition
            while body and (fm := FIELD_RE.match(body[0][1].strip())) and body[0][1][:1] != " ":
                key = fm.group(1).strip().lower()
                if key in fields:
                    field_lines.setdefault("__dup__", []).append((key, body[0][0]))
                fields[key], field_lines[key] = fm.group(2).strip(), body[0][0]
                body = body[1:]
            kids = parse_blocks(body)
            blocks.append(Block("def", line=ln, term=term, cond=cond, children=kids, fields=fields,
                                field_lines=field_lines, items=[["p", k.text, k.line] for k in kids if k.text]))
            continue
        kind = "key" if t.startswith("!") and not t.startswith("![") else "para"
        parts = [t[1:].strip() if kind == "key" else t.strip()]
        src = [(ln, parts[0])]
        i += 1
        while i < n and not is_block_start(lines[i][1]):
            if i + 1 < n and DEF_LINE_RE.match(lines[i + 1][1]):
                break   # next line is a definition term
            parts.append(lines[i][1].strip())
            src.append((lines[i][0], parts[-1]))
            i += 1
        blocks.append(Block(kind, " ".join(parts), ln, src=src, level=len(t) - len(t.lstrip())))

    for b in blocks:
        if b.kind not in ("para", "item", "note", "key"):
            continue
        if (m := BLOCK_COND_RE.match(b.text)) and (c := parse_cond(m.group(1))):
            b.cond, b.text = c, b.text[m.end():]
        if b.text.startswith("!") and not b.text.startswith("!["):
            b.text = b.text[1:].lstrip()
            if b.kind == "item":
                b.key = True
            elif b.kind == "para":
                b.kind = "key"
            if b.cond is None and (m := BLOCK_COND_RE.match(b.text)) and (c := parse_cond(m.group(1))):
                b.cond, b.text = c, b.text[m.end():]
        if b.cond is None and (m := HEADING_COND_RE.search(b.text)) and (c := parse_cond(m.group(1))):
            b.cond, b.text = c, b.text[: m.start()].rstrip()      # condition written at the end of the block
        if b.kind == "item" and (m := COMPONENT_RE.match(b.text)):
            b.qty = m.group(1)
    return blocks


def components_of(blocks: list[Block]) -> list[dict]:
    out, stack = [], []          # stack of (indent, name) for nested component lists
    for b in blocks:
        if b.kind != "item":
            stack = []
            continue
        if b.qty:
            rest = COMPONENT_RE.sub("", b.text, count=1)
            if rm := REF_RE.match(rest):
                while stack and stack[-1][0] >= b.level:
                    stack.pop()
                d = {"name": rm.group(1).strip(), "quantity": b.qty, "line": b.line}
                adds = [v for k, neg, v in (b.cond.tokens if b.cond else []) if k == "v" and not neg]
                if stack:
                    d["part_of"] = stack[-1][1]
                    adds = adds or stack[-1][2]          # nested parts belong to the same extension
                if adds:
                    d["added_by"] = adds
                stack.append((b.level, d["name"], adds))
                note = rest[rm.end():].strip(" —–-:,;")
                if note:
                    d["note"] = note
                if b.cond:
                    d["cond"] = b.cond.raw
                out.append(d)
    return out


def player_columns(b: Block):
    """For a player table: [(col_index, rng)], else None."""
    if not b.rows or len(b.rows[0][1]) < 2:
        return None
    cols = []
    for j, c in enumerate(b.rows[0][1][1:], start=1):
        m = P_TOKEN.match(c.strip())
        if not m or m.group(1):
            return None
        cols.append((j, parse_range(m.group(2))))
    return cols


def player_rows(b: Block):
    """Table with player codes in its first column: {row_index: rng}, else None."""
    body = [(k, cells) for k, (_, cells) in enumerate(b.rows) if k > 0 and not is_sep_row(cells)]
    if not body:
        return None
    out = {}
    for k, cells in body:
        m = P_TOKEN.match(cells[0].strip()) if cells else None
        if not m or m.group(1):
            return None
        out[k] = parse_range(m.group(2))
    return out
