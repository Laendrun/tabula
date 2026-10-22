"""Parsing a game body into blocks: headings, paragraphs, lists, tables, definitions…"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from .syntax import (
    BLOCK_COND_RE, COMPONENT_RE, Cond, DEF_LINE_RE, END_RE, FENCE_RE, FIELD_RE, HEADING_COND_RE,
    HEADING_RE, IMAGE_RE, ITEM_RE, P_TOKEN, REF_RE, parse_attrs, parse_choice, parse_cond, parse_range, split_bars,
    CHOICE_RE, bounds, in_range,
)

QUIET_END = "---\x00quiet"     # see fragments.expand_includes
SCOPE_MARK = "\x00scope "      # "## \x00scope Title {+x}": an invisible heading carrying an included section's condition


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
    callout: str = ""         # note: "> [!exemple] Title": its type as written (the title goes in `term`)
    hidden: bool = False      # heading: invisible, only scopes a condition (![[frag#Section {+x}]])
    totals: dict = field(default_factory=dict)  # filtered view, def: key -> [[tokens, number]] (totals.py)


def is_block_start(t: str) -> bool:
    s = t.lstrip()
    return (not s or bool(HEADING_RE.match(t)) or bool(END_RE.match(t)) or s.startswith("|") or bool(ITEM_RE.match(t))
            or s.startswith(">") or (t.startswith("!") and not t.startswith("![")) or bool(FENCE_RE.match(t))
            or bool(DEF_LINE_RE.match(t)) or bool(BLOCK_COND_RE.match(t)))


IMAGE_FIELD = "image"       # a card's picture: image:: media/cards/gift.png


def card_image(d: "Block") -> str | None:
    """The picture of a card (its image:: field), or None."""
    v = (d.fields or {}).get(IMAGE_FIELD, "").strip()
    return v or None


def shown_fields(d: "Block") -> dict:
    """A definition's fields, without its picture (drawn, not listed)."""
    return {k: v for k, v in (d.fields or {}).items() if k != IMAGE_FIELD}


CALLOUT_RE = re.compile(r"^\[!([^\]\s]+)\]\s*(.*)$")

# callout types, by family (accents and case ignored): how tools draw them
CALLOUT_FAMILIES = {
    "example": ("example", "examples", "exemple", "exemples", "beispiel", "esempio", "ejemplo"),
    "warning": ("warning", "attention", "important", "caution", "avertissement", "achtung", "wichtig", "danger"),
    "tip": ("tip", "tips", "astuce", "conseil", "conseils", "tipp", "hint", "strategie", "strategy", "idee", "idea"),
    "info": ("info", "note", "remarque", "precision", "clarification", "rappel", "hinweis", "reminder", "nb"),
    "question": ("question", "faq", "frage", "questions"),
}


def callout_family(kind: str) -> str:
    """"Précision" -> "info"; an unknown type -> "note"."""
    import unicodedata
    k = "".join(c for c in unicodedata.normalize("NFKD", kind.lower()) if not unicodedata.combining(c))
    return next((fam for fam, names in CALLOUT_FAMILIES.items() if k in names), "note")


def callout_title(b: "Block") -> str:
    """The title shown on a callout: its own, else its type with a capital ("exemple" -> "Exemple")."""
    return b.term or (b.callout[:1].upper() + b.callout[1:])


def table_cells(row: str) -> list[str]:
    """The cells of a table row; a | inside [[a|b]] or escaped as \\| doesn't split."""
    s = row.strip()
    s = s[1:] if s.startswith("|") else s
    s = s[:-1] if s.endswith("|") and not s.endswith("\\|") else s
    return [c.strip() for c in split_bars(s)]


def split_row(t: str) -> list[str]:
    """A table row's cells, as text: \\| is a literal |."""
    return [c.replace("\\|", "|") for c in table_cells(t)]


def is_sep_row(cells) -> bool:
    return any(cells) and all(re.fullmatch(r":?-{3,}:?|:?-+:?", c) for c in cells if c)


def parse_blocks(lines: list[tuple[int, str]]) -> list[Block]:
    blocks: list[Block] = []
    heads: list[Block] = []          # open sections, outermost first
    i, n = 0, len(lines)
    list_start: dict[int, int] = {}  # indentation -> the first number of the numbered list open there
    while i < n:
        ln, t = lines[i]
        if not t.strip():
            i += 1
            continue
        if not t[0].isspace() and not ITEM_RE.match(t):
            list_start.clear()       # a paragraph, heading… at the margin ends the lists
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
            hidden = title.startswith(SCOPE_MARK)
            if hidden:
                title = title[len(SCOPE_MARK):]
            key = title.startswith("!") and not title.startswith("![")       # "## ! Title": a key section
            if key:
                title = title[1:].lstrip()
            if (cm := HEADING_COND_RE.search(title)) and (attrs := parse_attrs(cm.group(1))):
                (cond, roles), title = attrs, title[: cm.start()]
            blocks.append(Block("heading", title.strip(), ln, level=len(m.group(1)), cond=cond,
                                roles=[] if hidden else roles, key=key and not hidden, hidden=hidden))
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
            resolve_player_cells(blocks[-1])
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
            for lvl in [l for l in list_start if l > indent]:
                del list_start[lvl]
            if marker in "-*+":
                list_start.pop(indent, None)
            else:            # numbered: counted from the list's first number, even if filtering hides that step
                list_start.setdefault(indent, int(marker[:-1]))
            blocks.append(Block("item", text, ln, level=indent, ordered=marker not in "-*+", src=src,
                                start=list_start.get(indent, 1)))
            continue
        if t.lstrip().startswith(">"):
            parts, src, inner = [], [], []
            level = len(t) - len(t.lstrip())
            while i < n and lines[i][1].lstrip().startswith(">"):
                raw = lines[i][1].lstrip()[1:]
                inner.append((lines[i][0], (raw[1:] if raw.startswith(" ") else raw).rstrip()))   # indentation kept
                parts.append(raw.strip())
                src.append((lines[i][0], parts[-1]))
                i += 1
            note = Block("note", "", ln, src=src, level=level)
            if parts and (cm := CALLOUT_RE.match(parts[0])):         # > [!exemple] Optional title
                note.callout, note.term = cm.group(1), cm.group(2).strip()
                parts, inner = parts[1:], inner[1:]
                src[0] = (src[0][0], cm.group(2).strip())
            body = [(k, s) for k, s in inner]
            while body and not body[0][1].strip():
                body.pop(0)
            structured = any(ITEM_RE.match(s) or s.lstrip().startswith("|") for _, s in body) or \
                any(not s.strip() for _, s in body)
            if structured:            # paragraphs ("> " blank lines between them) or a list: read as blocks
                note.children = parse_blocks(body)
            else:
                note.text = " ".join(p for p in parts if p) if note.callout else " ".join(parts)
            blocks.append(note)
            continue
        if (im := IMAGE_RE.fullmatch(t.strip())) and not im.group(1).startswith("sym:"):   # not a symbol
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
                value, field_ln = fm.group(2).strip(), body[0][0]
                body = body[1:]
                while body and body[0][1][:1] == " " and body[0][1].strip():   # indented lines continue it
                    value = f"{value} {body[0][1].strip()}".strip()
                    body = body[1:]
                fields[key], field_lines[key] = value, field_ln
            kids = parse_blocks(body)
            blocks.append(Block("def", line=ln, term=term, cond=cond, children=kids, fields=fields,
                                field_lines=field_lines, items=[["p", k.text, k.line] for k in kids if k.text]))
            continue
        kind = "key" if t.startswith("!") and not t.startswith("![") else "para"
        parts = [t[1:].strip() if kind == "key" else t.strip()]
        src = [(ln, parts[0])]
        i += 1
        while i < n:
            nt = lines[i][1]
            more_key = kind == "key" and nt.startswith("!") and not nt.startswith("![")
            if is_block_start(nt) and not more_key:
                break       # consecutive "! " lines are one key rule, like consecutive "> " lines are one note
            if i + 1 < n and DEF_LINE_RE.match(lines[i + 1][1]):
                break   # next line is a definition term
            parts.append(nt[1:].strip() if more_key else nt.strip())
            src.append((lines[i][0], nt.strip()))
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


def choice_for(text: str, n: int) -> str:
    """Inline choices that only depend on the player count, resolved for n players ({2p: 7 | *: 5} -> 5 at 3p)."""
    def repl(m):
        branches = parse_choice(m.group(1))
        if not branches or any(k not in ("p", "*") for c, _ in branches for k, _, _ in c.tokens):
            return m.group(0)
        for c, text in branches:
            if all(k == "*" or in_range(val, n) != neg for k, neg, val in c.tokens):
                return text
        return m.group(0)
    return CHOICE_RE.sub(repl, text)


def resolve_player_cells(b: Block):
    """In a player table, a cell under "3p" (or in a "3p" row) shows its choices for 3 players."""
    cols = player_columns(b)
    rows = None if cols else player_rows(b)
    for k, (ln, cells) in enumerate(b.rows):
        if k == 0 or is_sep_row(cells):
            continue
        for j in range(1, len(cells)):
            rng = dict(cols).get(j) if cols else (rows or {}).get(k)
            lo, hi = bounds(rng) if rng else (0, 0)
            if rng and hi < 99:            # "4-5p": resolved when 4 and 5 players give the same text
                options = {choice_for(cells[j], n) for n in range(lo, int(hi) + 1) if in_range(rng, n)}
                if len(options) == 1:
                    cells[j] = options.pop()


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
