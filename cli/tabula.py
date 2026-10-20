#!/usr/bin/env python3
"""tabula — reference CLI for the Tabula game format (spec v0.7).

  tabula list  [-p N] [-l CODE]
  tabula show  GAME [-p N] [-v VARIANT ...] [-l CODE] [--json]
  tabula export GAME [-p N] [-e EXT] [-v VARIANT] [--all] [-s SECTION] [-o FILE]
  tabula cards GAME [-p N] [-e EXT] [--all] [--sort COLUMN]
  tabula lookup GAME [TERM] [-p N] [-e EXT] [-v VARIANT] [--all]
  tabula check [GAME ...] [--strict] [-d]

GAME is a slug, a path to a .game file, or a game folder.
The vault is --vault, else $TABULA_VAULT, else the current directory.
"""
from __future__ import annotations

import argparse
import dataclasses
import difflib
import json
import os
import re
import shutil
import sys
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path

try:
    import yaml
except ImportError:  # pragma: no cover
    sys.exit("tabula needs PyYAML:  pip install pyyaml")

__version__ = "0.7.0"

# =========================================================================== syntax

HEADING_RE = re.compile(r"^(#{1,6})\s+(.*?)\s*$")
ITEM_RE = re.compile(r"^(\s*)([-*+]|\d+[.)])\s+(.*)$")
DEF_LINE_RE = re.compile(r"^ {0,3}:(?:\s+(.*)|\s*)$")
FENCE_RE = re.compile(r"^\s*(```|~~~)")
END_RE = re.compile(r"^-{3,}\s*$")          # "---" alone on a line: end of the current section
REF_RE = re.compile(r"(?<!\\)\[\[([^\[\]|\n]+?)(?:\|([^\[\]\n]+?))?\]\]")
IMAGE_RE = re.compile(r"(?<!\\)!\[([^\]]*)\]\(([^)\s]+)\)")
LINK_RE = re.compile(r"(?<![!\\\[])\[([^\[\]]+)\]\(([^)\s]+)\)")
COMPONENT_RE = re.compile(r"^(\d+(?:-\d+)?)\s*[x×X]\s+[^\[\]\n]*?(?=\[\[)")   # "8x [[Gift]]", "8x cartes [[Gift]]"
BLOCK_COND_RE = re.compile(r"^(?<!\\)\{([^{}:|\n]+)\}\s*")
HEADING_COND_RE = re.compile(r"\s+(?<!\\)\{([^{}:|\n]+)\}\s*$")
CHOICE_RE = re.compile(r"(?<!\\)\{([^{}\n]*:[^{}\n]*)\}")
BRACES_RE = re.compile(r"(?<!\\)\{([^{}\n]*)\}")
ESCAPE_RE = re.compile(r"\\([\[\]{}!\\*#])")
FIELD_RE = re.compile(r"^([^\W\d][\w -]*?)::\s*(.*)$")
LANG_RE = re.compile(r"^[a-z]{2,3}(?:-[A-Za-z0-9]{2,8})?$")

P_TOKEN = re.compile(r"^(!?)(\d+(?:-\d+|\+)?(?:,\d+(?:-\d+|\+)?)*)p$")
V_TOKEN = re.compile(r"^([+-])([A-Za-z0-9][A-Za-z0-9_-]*)$")
ROLE_TOKEN = re.compile(r"^#([A-Za-z][A-Za-z0-9_-]*)$")
KNOWN_ROLES = ("components", "goal", "setup", "play", "scoring", "end", "glossary", "cards", "events",
               "variants", "notes", "faq")
CONDISH_RE = re.compile(r"(\d\s*p\b|^\s*[+!-]\w|\bp\s*=|^\s*\*\s*$)")


def norm(name: str) -> str:
    """Case- and plural-insensitive key: 'Cartes Chaussettes' == 'carte chaussette'."""
    words = []
    for w in name.lower().split():
        if len(w) > 3 and w[-1] in "sx" and not w.endswith("ss"):
            w = w[:-1]
        words.append(w)
    return " ".join(words)


def split_lang(stem: str) -> tuple[str, str | None]:
    if "." in stem:
        base, lang = stem.rsplit(".", 1)
        if LANG_RE.match(lang):
            return base, lang
    return stem, None


# =========================================================================== ranges & conditions

RANGE_TOKEN_RE = re.compile(r"^(\d+)(?:-(\d+)|(\+))?$")


def parse_range(spec) -> list[tuple[int, float]] | None:
    """'3-5', '2', '5+', '2,4'  ->  [(lo, hi), ...] or None."""
    if spec is None:
        return None
    out = []
    for tok in str(spec).replace(" ", "").split(","):
        m = RANGE_TOKEN_RE.match(tok)
        if not m:
            return None
        lo = int(m.group(1))
        hi = float("inf") if m.group(3) else int(m.group(2) or lo)
        if hi < lo:
            return None
        out.append((lo, hi))
    return out or None


def in_range(rng, n: int) -> bool:
    return any(lo <= n <= hi for lo, hi in rng)


def bounds(rng) -> tuple[int, float]:
    return min(lo for lo, _ in rng), max(hi for _, hi in rng)


@dataclass
class Cond:
    raw: str
    tokens: list  # [("p", neg, rng) | ("v", neg, name) | ("*", False, None)]

    @property
    def variants(self):
        return [v for k, _, v in self.tokens if k == "v"]


def parse_attrs(s: str) -> tuple[Cond | None, list[str]] | None:
    """Heading braces: '#glossary', '+supercharge #cards', '4p' -> (condition, roles); None if invalid."""
    roles, rest = [], []
    for t in s.split():
        if m := ROLE_TOKEN.match(t):
            roles.append(m.group(1).lower())
        else:
            rest.append(t)
    if not rest:
        return (None, roles) if roles else None
    cond = parse_cond(" ".join(rest))
    return (cond, roles) if cond else None


def parse_cond(s: str) -> Cond | None:
    toks = s.split()
    if not toks:
        return None
    out = []
    for t in toks:
        if t == "*":
            out.append(("*", False, None))
            continue
        if m := P_TOKEN.match(t):
            rng = parse_range(m.group(2))
            if rng is None:
                return None
            out.append(("p", bool(m.group(1)), rng))
            continue
        if m := V_TOKEN.match(t):
            out.append(("v", m.group(1) == "-", m.group(2).lower()))
            continue
        return None
    return Cond(" ".join(toks), out)


@dataclass
class Ctx:
    """What the reader chose. Anything not chosen stays visible and is marked with a badge."""
    players: int | None = None                         # None: every player count
    variants: set[str] = field(default_factory=set)   # extensions/variants turned on
    everything: bool = False                           # --all: every extension and variant

    @property
    def active(self) -> bool:      # is anything hidden at all?
        return self.players is not None or not self.everything


def cond_ok(cond: Cond | None, ctx: Ctx) -> bool:
    if cond is None:
        return True
    for kind, neg, val in cond.tokens:
        if kind == "p" and ctx.players is not None:
            if in_range(val, ctx.players) == neg:
                return False
        elif kind == "v" and not ctx.everything:
            if (val in ctx.variants) == neg:      # extensions and variants are opt-in
                return False
    return True


def open_label(cond: Cond | None, ctx: Ctx) -> str:
    """The parts of a condition the reader hasn't decided (shown as a badge)."""
    if cond is None:
        return ""
    raw = cond.raw.split()
    keep = [raw[i] for i, (kind, _, _) in enumerate(cond.tokens)
            if (kind == "p" and ctx.players is None) or (kind == "v" and ctx.everything)]
    return " ".join(keep)


def parse_choice(body: str):
    """'3p: 17 | 4p: 13 | *: 10' -> [(Cond, text)] or None if not a valid choice."""
    branches = []
    for part in body.split("|"):
        if ":" not in part:
            return None
        c, text = part.split(":", 1)
        cond = parse_cond(c)
        if cond is None:
            return None
        branches.append((cond, text.strip() if text.strip() else text.rstrip()))
    return branches or None


# =========================================================================== issues

@dataclass
class Issue:
    level: str
    path: Path
    line: int
    msg: str


class Issues(list):
    def error(self, path, line, msg):
        self.append(Issue("error", Path(path), line, msg))

    def warn(self, path, line, msg):
        self.append(Issue("warning", Path(path), line, msg))


# =========================================================================== reading

UNSAVED: dict[Path, str] = {}        # check --stdin: file contents from an editor, used instead of the disk


def read_source(path: Path, issues: Issues) -> tuple[dict, list[tuple[int, str]]]:
    text = UNSAVED.get(Path(path).resolve())
    if text is None:
        text = path.read_text(encoding="utf-8")
    text = text.lstrip("\ufeff").replace("\r\n", "\n")
    text = re.sub(r"<!--.*?-->", lambda m: "\n" * m.group(0).count("\n"), text, flags=re.S)
    if (i := text.find("<!--")) >= 0:
        issues.error(path, text.count("\n", 0, i) + 1, "unclosed comment '<!--' (missing '-->')")
        text = text[:i]
    lines = text.split("\n")
    meta: dict = {}
    start = 0
    if lines and lines[0].strip() == "---":
        end = next((k for k in range(1, len(lines)) if lines[k].strip() == "---"), None)
        if end is None:
            issues.error(path, 1, "frontmatter starts with '---' but is never closed")
        else:
            try:
                meta = yaml.safe_load("\n".join(lines[1:end])) or {}
                if not isinstance(meta, dict):
                    issues.error(path, 2, "frontmatter must be YAML 'key: value' lines")
                    meta = {}
            except yaml.YAMLError as e:
                mark = getattr(e, "problem_mark", None)
                issues.error(path, (mark.line + 2) if mark else 1,
                             f"invalid YAML in frontmatter: {getattr(e, 'problem', e)}")
            start = end + 1
    return meta, [(k + 1, lines[k].rstrip()) for k in range(start, len(lines))]


# =========================================================================== blocks

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
        if END_RE.match(t):
            # "---" ends the innermost section: what follows belongs to the section around it again.
            # It becomes an invisible heading that reopens that section (or no section at all).
            if heads:
                heads.pop()
            up = heads[-1] if heads else None
            blocks.append(Block("heading", up.text if up else "", ln, level=up.level if up else 0,
                                cond=up.cond if up else None, roles=list(up.roles) if up else [],
                                reopens=(up.reopens or up.line) if up else -1))
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


# --------------------------------------------------------------------------- filtering

def via_of(cond: Cond | None, ctx: Ctx) -> tuple:
    """Enabled extensions/variants that a matching condition asks for (used for highlighting)."""
    if cond is None or ctx.everything:
        return ()
    return tuple(v for k, neg, v in cond.tokens if k == "v" and not neg and v in ctx.variants)


def filter_blocks(blocks: list[Block], ctx: Ctx) -> list[Block]:
    out, stack, items = [], [], []      # stack: headings (level, ok); items: list nesting (indent, ok)
    for b in blocks:
        if b.kind == "heading":
            items = []
            while stack and stack[-1][0] >= b.level:
                stack.pop()
            stack.append((b.level, cond_ok(b.cond, ctx)))
            if all(ok for _, ok in stack):
                out.append(dataclasses.replace(b, via=via_of(b.cond, ctx)) if b.cond else b)
            continue
        inherited = False
        if b.kind == "item":
            while items and items[-1][0] >= b.level:
                items.pop()
            parent_ok = all(ok for _, ok, _ in items)
            inherited = any(t for _, _, t in items)
            items.append((b.level, parent_ok and cond_ok(b.cond, ctx), inherited or bool(via_of(b.cond, ctx))))
            if not parent_ok:              # nested under a hidden item: hidden too
                continue
        elif b.kind in ("note", "table", "para", "key") and b.level and items:    # indented under a list item
            if not all(ok for _, ok, _ in items):
                continue
            inherited = any(t for _, _, t in items)
        else:
            items = []
        if not all(ok for _, ok in stack) or not cond_ok(b.cond, ctx):
            continue
        if b.cond and (v := via_of(b.cond, ctx)):
            b = dataclasses.replace(b, via=v, tint=True)
        elif inherited:
            b = dataclasses.replace(b, tint=True)
        if b.kind == "table":
            b = filter_table(b, ctx)
            if not b.rows:
                continue
        if b.kind == "def" and b.children:
            b = dataclasses.replace(b, children=filter_blocks(b.children, ctx))
        out.append(b)
    # drop headings whose whole section was filtered away
    keep = []
    for k, b in enumerate(out):
        if b.kind == "heading":
            end = next((j for j in range(k + 1, len(out))
                        if out[j].kind == "heading" and out[j].level <= b.level
                        and not (out[j].reopens and out[j].level == b.level)), len(out))
            if not any(x.kind != "heading" for x in out[k + 1: end]):
                continue
            if b.reopens:     # "---" after a section that was filtered away: nothing to close any more
                prev = next((x for x in reversed(keep) if x.kind == "heading"), None)
                if prev is None or prev.level <= b.level:
                    continue
        keep.append(b)
    return keep


def section_names(blocks: list[Block]) -> list[str]:
    out = []
    for b in blocks:
        if b.kind == "heading" and not b.reopens:
            out += [f"#{r}" for r in b.roles] or [CHOICE_RE.sub("", b.text).strip()]
    return out


def select_sections(blocks: list[Block], names: list[str]) -> list[Block]:
    """Keep only the sections whose role (#glossary) or heading title matches one of `names`."""
    wanted = [n.lower().lstrip("#") for n in names]

    def matches(b: Block) -> bool:
        if any(r in wanted for r in b.roles):
            return True
        title = norm(re.sub(r"[^\w\s'-]", " ", plain(b.text, Ctx(everything=True))))
        return any(title == norm(w) or title.startswith(norm(w) + " ") for w in wanted)

    out, capture = [], None          # capture: level of the matched heading being copied
    for b in blocks:
        if b.kind == "heading":
            if capture is not None and b.level <= capture:
                capture = None
            if capture is None and matches(b):
                capture = b.level
        if capture is not None:
            out.append(b)
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


def filter_table(b: Block, ctx: Ctx) -> Block:
    cols = player_columns(b)
    prow = None if cols else player_rows(b)
    keep = None
    if cols and ctx.players is not None:
        keep = [0] + [j for j, rng in cols if rng and in_range(rng, ctx.players)]
    rows = []
    for k, (ln, cells) in enumerate(b.rows):
        if prow and ctx.players is not None and k in prow and not in_range(prow[k], ctx.players):
            continue
        if cells and (m := BLOCK_COND_RE.match(cells[0])) and (c := parse_cond(m.group(1))):
            if not cond_ok(c, ctx):
                continue
            v, lab = via_of(c, ctx), open_label(c, ctx)
            cells = [(f"\x02{lab}\x02" if lab else "") + (f"\x01{','.join(v)}\x01" if v else "")
                     + cells[0][m.end():]] + cells[1:]
        if keep is not None:
            cells = [cells[j] if j < len(cells) else "" for j in keep]
        rows.append((ln, cells))
    return Block("table", line=b.line, rows=rows, cond=b.cond, level=b.level)


# =========================================================================== vault & games

@dataclass
class Game:
    slug: str
    path: Path
    folder: Path | None
    meta: dict
    blocks: list[Block]
    lines: list[tuple[int, str]]
    issues: Issues
    language: str
    default_language: str
    languages: list[str]
    fallback: bool = False
    body_path: Path | None = None
    tr_meta: dict = field(default_factory=dict)

    @property
    def title(self) -> str:
        return str(self.meta.get("title") or self.slug)

    @property
    def base_dir(self) -> Path:
        return self.folder or self.path.parent

    def _options(self, key: str) -> dict[str, str]:
        v = self.meta.get(key)
        if isinstance(v, dict):
            return {str(k): "" if d is None else str(d) for k, d in v.items()}
        if isinstance(v, list):
            return {str(k): "" for k in v}
        return {}

    @property
    def variants(self) -> dict[str, str]:
        return self._options("variants")

    @property
    def extensions(self) -> dict[str, str]:
        return self._options("extensions")

    @property
    def options(self) -> dict[str, str]:
        """Everything a {+name} condition can refer to: variants and extensions."""
        return {**self.variants, **self.extensions}


class Vault:
    def __init__(self, root: Path):
        self.root = root.resolve()
        self.config: dict = {}
        self.issues = Issues()
        cfg = self.root / "vault.yaml"
        if cfg.exists():
            try:
                self.config = yaml.safe_load(cfg.read_text(encoding="utf-8")) or {}
            except yaml.YAMLError as e:
                self.issues.error(cfg, 1, f"invalid YAML: {e}")
        self.language = str(self.config.get("language") or "en")

    def discover(self) -> list[Path]:
        found = []
        for g in sorted(self.root.glob("*.game")):
            slug, lang = split_lang(g.stem)
            if lang is None:
                found.append(g)
            elif not (self.root / f"{slug}.game").exists():
                self.issues.error(g, 0, f"translation without the default-language file '{slug}.game'")
        for d in sorted(p for p in self.root.iterdir() if p.is_dir() and not p.name.startswith(".")):
            games = sorted(d.glob("*.game"))
            if not games:
                continue
            expected = d / f"{d.name}.game"
            for g in games:
                if split_lang(g.stem)[0] != d.name:
                    self.issues.error(g, 0, f"file should be named '{d.name}.game' (or '{d.name}.<lang>.game')")
            if expected in games:
                found.append(expected)
            else:
                self.issues.error(d, 0, f"missing default-language file '{expected.name}'")
        return found

    def find(self, ref: str) -> Path:
        p = Path(ref)
        if p.is_file() and p.suffix == ".game":
            slug, lang = split_lang(p.stem)
            return (p.parent / f"{slug}.game").resolve() if lang else p.resolve()
        if p.is_dir() and (p / f"{p.name}.game").exists():
            return (p / f"{p.name}.game").resolve()
        for cand in (self.root / ref / f"{ref}.game", self.root / f"{ref}.game"):
            if cand.exists():
                return cand
        games = self.discover()
        hits = [g for g in games if ref.lower() in g.stem.lower()]
        if len(hits) == 1:
            return hits[0]
        raise SystemExit(f"tabula: game '{ref}' not found in {self.root}\n"
                         f"  available: {', '.join(g.stem for g in games) or '(none)'}")

    def load(self, path: Path, lang: str | None = None) -> Game:
        issues = Issues()
        slug = path.stem
        folder = None if path.parent.resolve() == self.root else path.parent
        meta, lines = read_source(path, issues)
        default_lang = str(meta.get("language") or self.language)
        langs = {default_lang}
        for f in path.parent.glob(f"{slug}.*.game"):
            s, l = split_lang(f.stem)
            if s == slug and l:
                langs.add(l)
        languages = sorted(langs)
        body_path, tr_meta, fallback = path, {}, False
        if lang and lang != default_lang:
            tr = path.parent / f"{slug}.{lang}.game"
            if tr.exists():
                tr_meta, lines = read_source(tr, issues)
                merged = {**meta, **tr_meta}
                for key in ("variants", "extensions"):
                    if isinstance(meta.get(key), dict) and isinstance(tr_meta.get(key), dict):
                        merged[key] = {**meta[key], **tr_meta[key]}
                meta, body_path = merged, tr
            else:
                fallback = True
        language = lang if (lang and not fallback) else default_lang
        return Game(slug, path, folder, meta, parse_blocks(lines), lines, issues, language,
                    default_lang, languages, fallback, body_path, tr_meta)


def open_vault(arg: str | None, ref: str | None = None) -> Vault:
    if arg:
        return Vault(Path(arg))
    if os.environ.get("TABULA_VAULT"):
        return Vault(Path(os.environ["TABULA_VAULT"]))
    if ref and Path(ref).exists():
        p = Path(ref).resolve()
        for anc in [p] + list(p.parents):
            if (anc / "vault.yaml").exists():
                return Vault(anc)
        d = p if p.is_dir() else p.parent
        return Vault(d.parent if (d / f"{d.name}.game").exists() else d)
    return Vault(Path.cwd())


# =========================================================================== rendering

ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")


class Style:
    def __init__(self, on: bool, plain: bool = False):
        self.on = on
        self.plain = plain        # bare text (JSON, matching): no arrows or other decorations

    def _w(self, code, s):
        return f"\x1b[{code}m{s}\x1b[0m" if self.on and s else s

    def bold(self, s): return self._w("1", s)
    def dim(self, s): return self._w("2", s)
    def italic(self, s): return self._w("3", s)
    def cyan(self, s): return self._w("36", s)
    def yellow(self, s): return self._w("33", s)
    def green(self, s): return self._w("32", s)
    def red(self, s): return self._w("31", s)
    def magenta(self, s): return self._w("35", s)

    def tint(self, s):
        """Highlight a whole piece of already-styled text (keeps bold/italic, overrides colours)."""
        if not self.on or not s:
            return s
        s = re.sub(r"\x1b\[3[0-9]m", "", s)
        return "\x1b[35m" + s.replace("\x1b[0m", "\x1b[0m\x1b[35m") + "\x1b[0m"


def vlen(s: str) -> int:
    return len(ANSI_RE.sub("", s))


def wrap(text: str, width: int, first: str = "", rest: str | None = None) -> list[str]:
    rest = first if rest is None else rest
    lines, cur, prefix = [], "", first
    for w in text.split(" "):
        if not w:
            continue
        if cur and vlen(prefix) + vlen(cur) + 1 + vlen(w) > width:
            lines.append(prefix + cur)
            cur, prefix = w, rest
        else:
            cur = f"{cur} {w}" if cur else w
    lines.append(prefix + cur)
    return lines


def resolve_choices(text: str, ctx: Ctx, st: Style) -> str:
    def repl(m):
        branches = parse_choice(m.group(1))
        if branches is None:
            return m.group(0)
        remaining = [(c, t, any(k == "*" for k, _, _ in c.tokens)) for c, t in branches]
        remaining = [(c, t, star) for c, t, star in remaining if star or cond_ok(c, ctx)]
        concrete = [(c, t) for c, t, star in remaining if not star]
        if concrete:
            c, t = concrete[0]
            if not open_label(c, ctx):                 # fully decided: this alternative wins
                return st.magenta(t) if via_of(c, ctx) else t
            shown = " | ".join(f"{'*' if star else open_label(c, ctx)}: {t}" for c, t, star in remaining)
            return st.yellow("⟨") + shown + st.yellow("⟩")
        return next((t for _, t, star in remaining if star), "")
    text = CHOICE_RE.sub(repl, text)
    text = re.sub(r" {2,}", " ", text)
    return re.sub(r" ([.,])", r"\1", text).strip()


def find_section(blocks: list[Block], name: str) -> Block | None:
    """The heading a [[#Section]] link points to: by title (like any reference), else by role."""
    want = name.lstrip("#").strip()
    heads = [b for b in blocks if b.kind == "heading" and not b.reopens]
    return (next((b for b in heads if fold(b.text) == fold(want)), None)
            or next((b for b in heads if want.lower() in b.roles), None))


def ref_text(m: re.Match, st: Style) -> str:
    """How a [[reference]] reads in the terminal; [[#Section]] links get an arrow."""
    name, alias = m.group(1).strip(), (m.group(2) or "").strip()
    if not name.startswith("#"):
        return st.cyan(alias or name)
    title = name[1:].strip()
    if st.plain:
        return alias or title
    return st.cyan(alias) + st.dim(f" (→ {title})") if alias else st.cyan("→ " + title)


def render_inline(text: str, ctx: Ctx, st: Style) -> str:
    text = resolve_choices(text, ctx, st)
    text = REF_RE.sub(lambda m: ref_text(m, st), text)
    text = IMAGE_RE.sub(lambda m: st.dim(f"[image: {m.group(1) or m.group(2)}]"), text)
    text = LINK_RE.sub(lambda m: f"{m.group(1)} {st.dim('(' + m.group(2) + ')')}", text)
    text = re.sub(r"\*\*(.+?)\*\*", lambda m: st.bold(m.group(1)), text)
    text = re.sub(r"(?<!\w)__(?!\s)(.+?)(?<!\s)__(?!\w)", lambda m: st.bold(m.group(1)), text)
    text = re.sub(r"(?<![*\w])\*(?!\s)(.+?)(?<!\s)\*(?![*\w])", lambda m: st.italic(m.group(1)), text)
    text = re.sub(r"(?<!\w)_(?!\s)(.+?)(?<!\s)_(?!\w)", lambda m: st.italic(m.group(1)), text)
    return ESCAPE_RE.sub(r"\1", text)


def plain(text: str, ctx: Ctx) -> str:
    return render_inline(text, ctx, Style(False, plain=True))


def render_blocks(blocks: list[Block], ctx: Ctx, st: Style, width: int) -> list[str]:
    out: list[str] = []
    counters: dict[int, int] = {}
    heading_end = -1

    def badge(b):
        out = ""
        if lab := open_label(b.cond, ctx):     # not decided by the reader: show the condition
            out += st.yellow(f"[{lab}] ")
        if b.via:          # what an enabled extension/variant adds or changes
            out += st.magenta("[+" + " +".join(b.via) + "] ")
        return out

    def gap():
        if out and out[-1] != "" and len(out) - 1 != heading_end:
            out.append("")

    for b in blocks:
        nested = b.kind in ("note", "table", "para", "key") and b.level and counters
        if b.kind != "item" and not nested:
            counters.clear()
        txt = render_inline(b.text, ctx, st) if b.kind not in ("table", "code", "def") else ""
        if b.kind == "heading" and b.reopens:
            if out and out[-1] != "":
                out.append("")
            out.append(st.dim("· · ·"))
            heading_end = len(out) - 1
        elif b.kind == "heading":
            if out and out[-1] != "":
                out.append("")
            if b.key:
                txt = st.green("★ ") + txt
            if b.level == 1:
                out.append(badge(b) + st.bold(st.yellow(txt.upper())))
                out.append(st.dim("─" * min(width, max(vlen(txt), 3))))
            elif b.level == 2:
                out.append(badge(b) + st.bold(txt))
            else:
                out.append(badge(b) + st.bold(st.dim(txt)))
            heading_end = len(out) - 1
        elif b.kind == "para":
            gap()
            pad = " " * (b.level + 1) if nested else ""
            out += wrap(badge(b) + (st.tint(txt) if b.tint else txt), width, pad)
        elif b.kind == "key":
            gap()
            out += wrap(badge(b) + st.bold(txt), width, st.green("★ "), "  ")
        elif b.kind == "note":
            if b.level == 0 or not counters:
                gap()
            pad = " " * (b.level + (2 if b.level else 0))
            out += wrap(badge(b) + st.dim(txt), width, pad + st.dim("│ "))
        elif b.kind == "image":
            gap()
            out.append(st.dim(f"[image: {txt or b.term}  →  {b.term}]"))
        elif b.kind == "code":
            gap()
            out += ["    " + l for l in b.text.split("\n")]
        elif b.kind == "def":
            gap()
            out.append(badge(b) + st.bold(render_inline(b.term, ctx, st)))
            shown = {k: render_inline(v, ctx, st) for k, v in b.fields.items()}
            shown = {k: v for k, v in shown.items() if vlen(v)}      # e.g. points:: {+points: 42} without +points
            if shown:
                out += wrap("   ".join(f"{st.dim(k + ':')} {v}" for k, v in shown.items()), width, "    ", "    ")
            out += ["    " + l if l else "" for l in render_blocks(b.children, ctx, st, width - 4)]
        elif b.kind == "item":
            if not counters:
                gap()                                  # blank line before a new list
            for lvl in [l for l in counters if l > b.level]:
                del counters[lvl]
            if b.ordered:
                counters[b.level] = counters.get(b.level, b.start - 1) + 1
                marker = f"{counters[b.level]}."
            else:
                counters.setdefault(b.level, 0)
                marker = "•"
            pad = " " * b.level
            if b.tint:
                txt = st.tint(txt)
            body = badge(b) + (st.green("★ ") + st.bold(txt) if b.key else txt)
            out += wrap(body, width, f"{pad}{marker} ", pad + " " * (len(marker) + 1))
        elif b.kind == "table":
            if not nested:
                gap()
            pad = " " * (b.level + 1) if nested else ""
            out += [pad + l for l in render_table(b, ctx, st)]
    return out


def render_table(b: Block, ctx: Ctx, st: Style) -> list[str]:
    rows = []
    for _, cells in b.rows:
        if is_sep_row(cells):
            continue
        r = []
        for c in cells:
            badge = ""
            if (lm := re.match(r"\x02(.*?)\x02", c)):
                badge, c = st.yellow(f"[{lm.group(1)}] "), c[lm.end():]
            if (vm := re.match(r"\x01(.*?)\x01", c)):
                badge, c = badge + st.magenta(f"[+{vm.group(1).replace(',', ' +')}] "), c[vm.end():]
            r.append(badge + render_inline(c, ctx, st))
        rows.append(r)
    if not rows:
        return []
    ncol = max(len(r) for r in rows)
    rows = [r + [""] * (ncol - len(r)) for r in rows]
    widths = [max(vlen(r[j]) for r in rows) for j in range(ncol)]
    fmt = lambda r: "  ".join(c + " " * (widths[j] - vlen(c)) for j, c in enumerate(r)).rstrip()
    return [st.bold(fmt(rows[0])), st.dim("  ".join("─" * w for w in widths))] + [fmt(r) for r in rows[1:]]


# =========================================================================== show / list

def meta_line(meta: dict) -> str:
    bits = []
    if meta.get("players") is not None:
        bits.append(f"{meta['players']} players")
    if meta.get("best_players") is not None:
        bits.append(f"best {meta['best_players']}")
    if meta.get("duration") is not None:
        bits.append(f"{meta['duration']} min")
    if meta.get("age") is not None:
        bits.append(f"age {str(meta['age']).rstrip('+')}+")
    t = meta.get("type")
    if t:
        bits.append(", ".join(map(str, t)) if isinstance(t, list) else str(t))
    return " · ".join(bits)


def block_json(b: Block, ctx: Ctx) -> dict:
    if b.kind == "heading" and b.reopens:
        return {"kind": "end", "line": b.line}
    d: dict = {"kind": b.kind, "line": b.line}
    if b.cond:
        d["cond"] = b.cond.raw
    if b.via:
        d["from"] = list(b.via)
    if b.kind == "heading":
        d["level"] = b.level
        if b.roles:
            d["roles"] = b.roles
        if b.key:
            d["key"] = True
    if b.kind == "table":
        d["player_table"] = player_columns(b) is not None
        d["rows"] = [[plain(re.sub(r"\x01.*?\x01", "", c), ctx) for c in cells] for _, cells in b.rows if not is_sep_row(cells)]
    elif b.kind == "def":
        d["term"] = b.term
        if b.fields:
            d["fields"] = {k: plain(v, ctx) for k, v in b.fields.items()}
        d["body"] = [block_json(k, ctx) for k in b.children]
    elif b.kind == "code":
        d["text"] = b.text
    else:
        d["text"] = plain(b.text, ctx)
        if b.kind == "image":
            d["src"] = b.term
        if b.kind == "item":
            d.update(ordered=b.ordered, indent=b.level, key=b.key)
            if b.qty:
                d["component"] = True
    return d


def cmd_show(args) -> int:
    vault = open_vault(args.vault, args.game)
    game = vault.load(vault.find(args.game), args.lang)
    if args.all and (args.ext or args.variant):
        print("tabula: --all already shows every extension and variant; drop either --all or -e/-v", file=sys.stderr)
        return 2
    ctx = Ctx(args.players, {v.lower() for v in (args.variant or []) + (args.ext or [])}, args.all)
    if game.fallback:
        print(f"tabula: {game.title} has no '{args.lang}' version (available: {', '.join(game.languages)}); "
              f"showing '{game.default_language}'", file=sys.stderr)
    rng = parse_range(game.meta.get("players"))
    if args.players is not None and rng and not in_range(rng, args.players):
        print(f"tabula: {game.title} is for {game.meta.get('players')} players, not {args.players}", file=sys.stderr)
        return 2
    declared = game.variants
    for v in ctx.variants:
        if v not in {k.lower() for k in game.options}:
            print(f"tabula: '{v}' is not a variant or extension of {game.title}; "
                  f"variants: {', '.join(game.variants) or '(none)'}; extensions: {', '.join(game.extensions) or '(none)'}",
                  file=sys.stderr)
            return 2

    blocks = filter_blocks(game.blocks, ctx)
    if args.section:
        picked = select_sections(blocks, args.section)
        if not picked:
            avail = section_names(blocks)
            print(f"tabula: no section {', '.join(args.section)} in {game.title}; "
                  f"available: {', '.join(avail) or '(none)'}", file=sys.stderr)
            return 2
        blocks = picked
    if args.json:
        print(json.dumps({
            "slug": game.slug, "title": game.title, "path": str(game.body_path or game.path),
            "language": game.language, "languages": game.languages, "meta": game.meta,
            "filters": {"players": ctx.players, "options": sorted(ctx.variants), "all": ctx.everything},
            "components": [{k: v for k, v in c.items() if k != "line"} for c in components_of(blocks)],
            "glossary": [{"term": b.term, "definition": [plain(k.text, ctx) for k in b.children if k.text]}
                         for b in blocks if b.kind == "def"],
            "key_rules": [plain(b.text, ctx) for b in blocks if b.kind == "key" or (b.kind == "item" and b.key)],
            "key_sections": [plain(b.text, ctx) for b in blocks if b.kind == "heading" and b.key],
            "blocks": [block_json(b, ctx) for b in blocks],
        }, indent=2, ensure_ascii=False, default=str))
        return 0

    st = Style(sys.stdout.isatty() and not os.environ.get("NO_COLOR") and not args.no_color)
    width = min(shutil.get_terminal_size((88, 20)).columns, 88)
    out = [st.bold(game.title)]
    if ml := meta_line(game.meta):
        out.append(st.dim(ml))
    f = [f"{ctx.players} players"] if ctx.players is not None else []
    if ctx.everything:
        if game.options:
            f.append("everything (all extensions and variants)")
    else:
        f += [f"+{v}" for v in sorted(ctx.variants)]
        if game.extensions and not (ctx.variants & {k.lower() for k in game.extensions}):
            f.append("base game")
        if game.variants and not (ctx.variants & {k.lower() for k in game.variants}):
            f.append("no variants")
    if f:
        out.append(st.green("Showing: " + ", ".join(f)))
    if ctx.variants:
        out.append(st.magenta("[+…]") + st.dim(" marks what the enabled extensions/variants add or change"))
    info = []
    if len(game.languages) > 1:
        info.append(f"language: {game.language} (available: {', '.join(game.languages)}; -l CODE)")
    if game.extensions:
        info.append("extensions: " + ", ".join(game.extensions) + " (-e NAME)")
    if declared:
        info.append("variants: " + ", ".join(declared) + " (-v NAME)")
    if game.options and not ctx.everything:
        info.append("--all shows everything")
    if info:
        out.append(st.dim(" · ".join(info)))
    out.append("")
    out += render_blocks(blocks, ctx, st, width)
    print("\n".join(out).rstrip() + "\n")
    if any(i.level == "error" for i in game.issues):
        print(f"tabula: this file has errors; run 'tabula check {game.slug}'", file=sys.stderr)
    return 0


# --------------------------------------------------------------------------- lookup

def fold(text: str) -> str:
    """Search key: case, accents and plurals ignored ('Événements' == 'evenement')."""
    text = unicodedata.normalize("NFKD", text)
    text = "".join(c for c in text if not unicodedata.combining(c))
    return norm(re.sub(r"[^\w\s'-]", " ", text))


@dataclass
class Entry:
    name: str
    kind: str                  # "definition" | "component"
    blocks: list               # what to render (the definition, or the component line and its parts)
    cond: Cond | None = None


def lookup_entries(blocks: list[Block]) -> list[Entry]:
    """Every glossary term and every component of a game (definitions first)."""
    defs, comps, seen = [], [], set()

    def walk(bs):
        for b in bs:
            if b.kind == "def":
                defs.append(Entry(b.term, "definition", [b], b.cond))
                walk(b.children)

    walk(blocks)
    seen = {fold(e.name) for e in defs}
    for k, b in enumerate(blocks):
        if b.kind == "item" and b.qty and (rm := REF_RE.search(COMPONENT_RE.sub("", b.text, count=1))):
            name = rm.group(1).strip()
            if fold(name) in seen:
                continue
            parts = [b] + list(_nested_items(blocks, k))
            existing = next((e for e in comps if fold(e.name) == fold(name)), None)
            if existing:
                existing.blocks += parts
            else:
                comps.append(Entry(name, "component", parts, b.cond))
    return defs + comps


def _nested_items(blocks: list[Block], k: int):
    for b in blocks[k + 1:]:
        if b.kind != "item" or b.level <= blocks[k].level:
            return
        yield b


def find_entries(entries: list[Entry], query: str) -> tuple[list[Entry], str]:
    """Exact match, else names containing the query, else close spellings. Returns (matches, how)."""
    q = fold(query)
    exact = [e for e in entries if fold(e.name) == q]
    if exact:
        return exact, "exact"
    words = q.split()
    partial = [e for e in entries if all(w in fold(e.name) for w in words)]
    if partial:
        return partial, "partial"
    names = {fold(e.name): e for e in entries}
    close = difflib.get_close_matches(q, list(names), n=5, cutoff=0.6)
    return [names[c] for c in close], "close"


def see_also(entry: Entry, entries: list[Entry]) -> list[str]:
    """Other terms/components referenced inside an entry, in order of appearance."""
    known = {fold(e.name): e.name for e in entries}
    out = []

    def texts(bs):
        for b in bs:
            yield b.text
            yield from (c for _, cells in b.rows for c in cells)
            yield from texts(b.children)

    for t in texts(entry.blocks):
        for m in REF_RE.finditer(t or ""):
            if m.group(1).strip().startswith("#"):
                continue          # a link to a section, not a term
            name = known.get(fold(m.group(1)))
            if name and fold(name) != fold(entry.name) and name not in out:
                out.append(name)
    return out


def cmd_lookup(args) -> int:
    vault = open_vault(args.vault, args.game)
    game = vault.load(vault.find(args.game), args.lang)
    if args.all and (args.ext or args.variant):
        print("tabula: --all already includes every extension and variant; drop either --all or -e/-v", file=sys.stderr)
        return 2
    ctx = Ctx(args.players, {v.lower() for v in (args.variant or []) + (args.ext or [])}, args.all)
    for v in ctx.variants:
        if v not in {k.lower() for k in game.options}:
            print(f"tabula: '{v}' is not a variant or extension of {game.title}", file=sys.stderr)
            return 2
    st = Style(sys.stdout.isatty() and not os.environ.get("NO_COLOR") and not args.no_color)
    width = min(shutil.get_terminal_size((88, 20)).columns, 88)
    entries = lookup_entries(game.blocks)

    if not args.term:                                   # no term: list every term
        visible = [e for e in entries if cond_ok(e.cond, ctx)]
        if args.json:
            print(json.dumps([{"term": e.name, "kind": e.kind} for e in visible], indent=2, ensure_ascii=False))
            return 0
        print(st.bold(f"{game.title}: {len(visible)} terms") + st.dim("  (tabula lookup GAME TERM)"))
        for kind, label in (("definition", "Glossary"), ("component", "Components without definition")):
            names = sorted((e.name for e in visible if e.kind == kind), key=fold)
            if names:
                print("\n" + st.bold(label))
                print("\n".join(wrap(", ".join(names), width)))
        return 0

    term = " ".join(args.term)
    matches, how = find_entries(entries, term)
    if how != "exact":                                   # no term by that name: maybe a section (#components…)
        section = select_sections(filter_blocks(game.blocks, ctx), [term])
        if section:
            if args.json:
                print(json.dumps({"query": term, "match": "section",
                                  "blocks": [block_json(b, ctx) for b in section]}, indent=2, ensure_ascii=False,
                                 default=str))
            else:
                print("\n".join(render_blocks(section, ctx, st, width)).rstrip())
            return 0
    if not matches:
        print(f"tabula: nothing called '{term}' in {game.title} (tabula lookup {game.slug} lists every term)",
              file=sys.stderr)
        return 1
    others = []
    if how == "close":                                   # a typo: show the best guess, name the others
        matches, others = matches[:1], [e.name for e in matches[1:]]
    if len(matches) > args.max:
        print(f"{len(matches)} terms match '{term}', be more precise:")
        print("\n".join(wrap(", ".join(e.name for e in matches), width, "  ")))
        return 1

    results = []
    for e in matches:
        shown = filter_blocks(e.blocks, ctx)
        hidden = not shown or not cond_ok(e.cond, ctx)
        if hidden:                                        # not in the current selection: show it anyway, marked
            shown = filter_blocks(e.blocks, Ctx(players=ctx.players, everything=True))
        results.append((e, shown, hidden, see_also(e, entries)))

    if args.json:
        print(json.dumps({"query": term, "match": how, "results": [
            {"term": e.name, "kind": e.kind, "cond": e.cond.raw if e.cond else None,
             "in_selection": not hidden, "blocks": [block_json(b, ctx) for b in shown], "see_also": also}
            for e, shown, hidden, also in results]}, indent=2, ensure_ascii=False, default=str))
        return 0

    out = []
    if how == "close":
        out.append(st.dim(f"No exact match for '{term}', showing the closest:"))
    for e, shown, hidden, also in results:
        if out:
            out.append("")
        sub_ctx = ctx if not hidden else Ctx(players=ctx.players, everything=True)
        out += render_blocks(shown, sub_ctx, st, width)
        if hidden:
            out.append(st.dim(f"    (only with {e.cond.raw})" if e.cond else "    (not in the current selection)"))
        if also:
            out += wrap(st.dim("see also: ") + ", ".join(st.cyan(a) for a in also), width, "    ", "    ")
    if others:
        out += ["", st.dim("other close names: " + ", ".join(others))]
    print("\n".join(out).rstrip())
    return 0


# --------------------------------------------------------------------------- card catalog

def card_catalog(blocks: list[Block]) -> list[dict]:
    """Cards: definitions inside a {#cards} section (with its sub-sections), or, in a game without
    such a section, every definition that has fields. Each: {def, group, catalog (heading)}."""
    out, cat, cat_level, group = [], None, None, ""
    cats: dict[int, Block] = {}           # heading line -> #cards heading (for sections reopened by "---")
    for b in blocks:
        if b.kind == "heading":
            if cat_level is not None and b.level <= cat_level:
                cat, cat_level = None, None
            if "cards" in b.roles:
                cat = cats.get(b.reopens) or cats.setdefault(b.line, b)
                cat_level, group = b.level, b.text
            elif cat is not None:
                group = b.text
        elif b.kind == "def" and cat is not None:
            out.append({"def": b, "group": group, "catalog": cat})
    if out:
        return out
    return [{"def": b, "group": "", "catalog": None} for b in blocks if b.kind == "def" and b.fields]


def card_counts(blocks: list[Block]) -> dict[str, str]:
    """How many of each card are in play: the component lines that name it, added up."""
    totals: dict[str, list[str]] = {}
    for c in components_of(blocks):
        totals.setdefault(fold(c["name"]), []).append(c["quantity"])
    out = {}
    for k, qs in totals.items():
        out[k] = str(sum(int(q) for q in qs)) if all(q.isdigit() for q in qs) else " + ".join(qs)
    return out


def card_rows(catalog: list[dict], blocks: list[Block], ctx: Ctx):
    """Columns and rows for a catalog table (fields in order of first appearance)."""
    counts = card_counts(blocks)
    keys: list[str] = []
    for c in catalog:
        keys += [k for k in c["def"].fields if k not in keys and k != "count"]
    show_ext = any(c["def"].cond and c["def"].cond.variants for c in catalog)
    rows = []
    for c in catalog:
        d = c["def"]
        count = counts.get(fold(d.term), d.fields.get("count", ""))
        ext = " ".join("+" + v for v in (d.cond.variants if d.cond else []))
        rows.append({"card": d.term, "count": count, "ext": ext, "group": c["group"], "def": d,
                     **{k: d.fields.get(k, "") for k in keys}})
    cols = ["card"] + (["count"] if any(r["count"] for r in rows) else []) + keys + (["ext"] if show_ext else [])
    return cols, rows


def sort_rows(rows: list[dict], key: str | None) -> list[dict]:
    if not key:
        return rows
    def k(r):
        v = plain(str(r.get(key, "")), Ctx(everything=True))
        num = re.match(r"^-?\d+(\.\d+)?", v)
        return (0, float(num.group(0)), "") if num else (1, 0, fold(v))
    return sorted(rows, key=k)


def cmd_cards(args) -> int:
    vault = open_vault(args.vault, args.game)
    game = vault.load(vault.find(args.game), args.lang)
    if args.all and (args.ext or args.variant):
        print("tabula: --all already includes every extension and variant; drop either --all or -e/-v", file=sys.stderr)
        return 2
    ctx = Ctx(args.players, {v.lower() for v in (args.variant or []) + (args.ext or [])}, args.all)
    for v in ctx.variants:
        if v not in {k.lower() for k in game.options}:
            print(f"tabula: '{v}' is not a variant or extension of {game.title}", file=sys.stderr)
            return 2
    blocks = filter_blocks(game.blocks, ctx)
    catalog = card_catalog(blocks)
    if not catalog:
        if card_catalog(game.blocks):
            print(f"tabula: no cards in this selection; try --all or -e EXTENSION "
                  f"(extensions: {', '.join(game.extensions) or 'none'})", file=sys.stderr)
        else:
            print(f"tabula: {game.title} has no cards yet: put definitions in a section with the {{#cards}} role, "
                  f"or give them fields like 'points:: 3'", file=sys.stderr)
        return 1
    cols, rows = card_rows(catalog, blocks, ctx)
    if args.sort and args.sort not in cols:
        print(f"tabula: no column '{args.sort}'; columns: {', '.join(cols)}", file=sys.stderr)
        return 2
    if args.json:
        print(json.dumps([{c: plain(str(r.get(c, "")), ctx) for c in cols} | {"group": r["group"]} for r in rows],
                         indent=2, ensure_ascii=False))
        return 0
    st = Style(sys.stdout.isatty() and not os.environ.get("NO_COLOR") and not args.no_color)
    groups = {} if args.sort else {}
    order: list[str] = []
    for r in (sort_rows(rows, args.sort) if args.sort else rows):
        g = "" if args.sort else r["group"]
        if g not in groups:
            groups[g], _ = [], order.append(g)
        groups[g].append(r)
    out = []
    for g in order:
        table = [cols] + [[render_inline(str(r.get(c, "")), ctx, st) if c != "card" else st.bold(r["card"])
                           for c in cols] for r in groups[g]]
        widths = [max(vlen(row[j]) for row in table) for j in range(len(cols))]
        fmt = lambda row: "  ".join(cell + " " * (widths[j] - vlen(cell)) for j, cell in enumerate(row)).rstrip()
        if out:
            out.append("")
        if g:
            out.append(st.bold(st.yellow(render_inline(g, ctx, st))))
        out.append(st.dim(fmt(table[0])))
        out += [fmt(row) for row in table[1:]]
    total = len(rows)
    out += ["", st.dim(f"{total} card{'s' if total != 1 else ''}" + (" · sorted by " + args.sort if args.sort else ""))]
    print("\n".join(out))
    return 0


def cmd_list(args) -> int:
    vault = open_vault(args.vault)
    rows = []
    for p in vault.discover():
        g = vault.load(p, args.lang)
        rng = parse_range(g.meta.get("players"))
        if args.players is not None and not (rng and in_range(rng, args.players)):
            continue
        rows.append([g.slug, g.title, str(g.meta.get("players", "?")), str(g.meta.get("duration", "")),
                     ", ".join(g.languages), str(g.meta.get("location", "") or "")])
    if not rows:
        print("no games found" + (f" for {args.players} players" if args.players else "") + f" in {vault.root}")
        return 0
    header = ["slug", "title", "players", "min", "lang", "location"]
    widths = [max(len(r[j]) for r in rows + [header]) for j in range(len(header))]
    st = Style(sys.stdout.isatty() and not os.environ.get("NO_COLOR"))
    print(st.bold("  ".join(h.ljust(w) for h, w in zip(header, widths)).rstrip()))
    for r in rows:
        print("  ".join(c.ljust(w) for c, w in zip(r, widths)).rstrip())
    return 0


# =========================================================================== check

STRUCTURAL_KEYS = ("players", "best_players", "duration", "age", "year", "cover")


def check_game(game: Game, vault: Vault, require_defs: bool = False) -> Issues:
    iss = Issues()
    iss.extend(game.issues)
    path = game.body_path or game.path
    meta = game.meta

    # ---- frontmatter
    if not meta.get("title"):
        iss.error(path, 1, "missing required 'title' in frontmatter")
    if meta.get("players") is None:
        iss.error(path, 1, "missing required 'players' in frontmatter (e.g. players: 2-4)")
    elif parse_range(meta["players"]) is None:
        iss.error(path, 1, f"invalid players '{meta['players']}' (use N, N-M, N+ or N,M)")
    if meta.get("best_players") is not None and parse_range(meta["best_players"]) is None:
        iss.warn(path, 1, f"invalid best_players '{meta['best_players']}'")
    if meta.get("duration") is not None and parse_range(meta["duration"]) is None:
        iss.warn(path, 1, f"duration should be minutes, e.g. 30 or 30-60 (got '{meta['duration']}')")
    if meta.get("age") is not None and not str(meta["age"]).rstrip("+").isdigit():
        iss.warn(path, 1, f"age should be a number (got '{meta['age']}')")
    if meta.get("cover") and not (game.base_dir / str(meta["cover"])).exists():
        iss.error(path, 1, f"cover image not found: {meta['cover']}")
    v = meta.get("variants")
    if v is not None and not isinstance(v, (dict, list)):
        iss.error(path, 1, "'variants' must be a mapping (name: description) or a list of names")
    for key in ("rules",):
        if key in meta:
            iss.warn(path, 1, f"'{key}:' in frontmatter is from v0.3; move 'variants' (and others) to the top level")

    game_rng = parse_range(meta.get("players"))
    declared = {k.lower() for k in game.options}
    ext = meta.get("extensions")
    if ext is not None and not isinstance(ext, (dict, list)):
        iss.error(path, 1, "'extensions' must be a mapping (name: description) or a list of names")
    for both in set(game.variants) & set(game.extensions):
        iss.warn(path, 1, f"'{both}' is declared both as a variant and as an extension")

    # ---- leftover v0.3 syntax (raw lines)
    in_code = False
    for ln, t in game.lines:
        if FENCE_RE.match(t):
            in_code = not in_code
        if in_code:
            continue
        if re.match(r"^=+\s", t):
            iss.warn(path, ln, "headings use '#' in v0.4 ('# Title', '## Sub'), not '='")
        if re.match(r"^\+\+\+ rules\s*$", t):
            iss.warn(path, ln, "'+++ rules' is no longer used (v0.4); just remove the line")
        if re.search(r"(?<![\w/&.])@[A-Za-zÀ-ÿ]", t):
            iss.warn(path, ln, "old '@component' syntax? v0.4 uses [[component]]")
        if re.search(r"(?<![\w/&#\[(])#[A-Za-zÀ-ÿ]", t) and not t.lstrip().startswith("#"):
            iss.warn(path, ln, "old '#keyword' syntax? v0.4 uses [[term]] and a definition")
        if "[p=" in t:
            iss.error(path, ln, "old '[p=…]' condition syntax; v0.4 uses {2p}, {3-4p: text | *: text}")
    if game.folder:
        for f in game.folder.glob("*.rules"):
            iss.warn(f, 0, "separate .rules files are not read in v0.4; move their content into the .game file")

    # ---- conditions
    def check_cond(c: Cond, ln, in_choice: bool = False):
        if not in_choice and any(k == "*" for k, _, _ in c.tokens):
            iss.error(path, ln, f"'{{{c.raw}}}': '*' (otherwise) only works inside an inline choice "
                                f"{{+x: … | *: …}}; for a line shown only without an option, write {{-name}}")
        for kind, neg, val in c.tokens:
            if kind == "p" and game_rng:
                lo, hi = bounds(game_rng)
                hits = [n for n in range(lo, int(min(hi, 99)) + 1) if in_range(game_rng, n) and in_range(val, n) != neg]
                if not hits:
                    iss.warn(path, ln, f"condition '{c.raw}' never applies (game is for {meta.get('players')} players)")
            elif kind == "v" and val not in declared:
                iss.error(path, ln, f"'+{val}' is not declared; add it under 'variants:' or 'extensions:' "
                                    f"in the frontmatter")

    refs: list[tuple[str, int, str]] = []
    singles: list[tuple[str, int]] = []      # [name] with single brackets: maybe a mistyped [[name]]

    def check_text(text: str, ln: int, allow_block_cond: bool = False):
        rest = text
        if allow_block_cond and (m := BLOCK_COND_RE.match(rest)) and (c := parse_cond(m.group(1))):
            check_cond(c, ln)
            rest = rest[m.end():]
        for m in CHOICE_RE.finditer(rest):
            br = parse_choice(m.group(1))
            if br:
                for c, _ in br:
                    check_cond(c, ln, in_choice=True)
                if sum(1 for c, _ in br if any(k == "*" for k, _, _ in c.tokens)) > 1:
                    iss.warn(path, ln, "choice has more than one '*' alternative")
        for m in BRACES_RE.finditer(rest):
            body = m.group(1)
            if parse_choice(body) if ":" in body else False:
                continue
            if parse_cond(body):
                iss.error(path, ln, f"'{{{body}}}' in the middle of text: a block condition goes at the start or "
                                    f"the end of a line; inside a sentence write '{{{body}: text}}'")
            elif CONDISH_RE.search(body.split(":")[0]):
                iss.error(path, ln, f"invalid condition '{{{body}}}' (codes: 2p, 3-4p, 5+p, !2p, +variant, "
                                    f"-variant; choices: {{3p: … | *: …}})")
        for m in REF_RE.finditer(rest):
            refs.append((m.group(1).strip(), ln, m.group(0)))
        for m in re.finditer(r"(?<![\[!\\])\[([^\[\]\n]+)\](?![\](\[])", REF_RE.sub("", rest)):
            singles.append((m.group(1).strip(), ln))
        if (nm := re.search(r"(?<!\\)\[\[([^\[\]\n]*)\[\[([^\[\]\n]*)\]\]", rest)):
            inner = f"{nm.group(1).strip()} {nm.group(2).strip()}".strip()
            iss.error(path, ln, f"a reference inside another reference: write [[{inner}]] "
                                f"(section links ignore the brackets in the heading)")
        elif re.search(r"(?<!\\)\[\[(?![^\]]*\]\])", REF_RE.sub("", rest)):
            iss.error(path, ln, "unclosed '[[' reference")
        for m in IMAGE_RE.finditer(rest):
            src = m.group(2)
            if not re.match(r"^[a-z]+://", src) and not (game.base_dir / src).exists():
                iss.error(path, ln, f"image not found: {src}")

    terms: dict[str, tuple[int, str]] = {}
    bracketed: set[str] = set()      # terms written as [[Term]]: reported once, not at every reference

    def walk(blocks: list[Block]):
        for b in blocks:
            if b.kind == "heading" and b.reopens:
                continue          # "---": its condition belongs to the section it reopens
            if b.cond:
                check_cond(b.cond, b.line)
            if b.kind == "heading":
                if (cm := HEADING_COND_RE.search(b.text)) and not parse_attrs(cm.group(1)):
                    iss.error(path, b.line, f"invalid heading attributes '{{{cm.group(1)}}}' (roles look like "
                                            f"#glossary, conditions like 2p or +name)")
                    continue
                check_text(b.text, b.line)
            elif b.kind in ("para", "item", "note", "key"):
                src = b.src or [(b.line, b.text)]
                for k, (ln, raw) in enumerate(src):
                    if k == 0:   # the block condition / "!" were already taken off b.text
                        raw = raw.lstrip("! ")
                        if (m := BLOCK_COND_RE.match(raw)) and parse_cond(m.group(1)):
                            raw = raw[m.end():].lstrip("! ")
                    if k == len(src) - 1 and (m := HEADING_COND_RE.search(raw)) and parse_cond(m.group(1)):
                        raw = raw[: m.start()]       # condition written at the end of the block
                    check_text(raw, ln)
                if re.sub(r"`[^`]*`|\\\*", "", b.text).count("**") % 2:
                    iss.warn(path, b.line, "'**' is opened but never closed (bold text needs '**' on both sides)")
            elif b.kind == "image":
                if not re.match(r"^[a-z]+://", b.term) and not (game.base_dir / b.term).exists():
                    iss.error(path, b.line, f"image not found: {b.term}")
            elif b.kind == "def":
                if (rm := REF_RE.fullmatch(b.term)):
                    iss.error(path, b.line, f"term '{b.term}' is written as a reference; "
                                            f"write it without brackets: '{rm.group(1).strip()}'")
                    bracketed.add(norm(rm.group(1)))
                k = norm(b.term)
                if k in terms:
                    iss.warn(path, b.line, f"'{b.term}' is defined twice (also line {terms[k][0]})")
                else:
                    terms[k] = (b.line, b.term)
                if not b.children and not b.fields:
                    iss.warn(path, b.line, f"definition of '{b.term}' is empty")
                for key, val in b.fields.items():
                    if not val:
                        iss.warn(path, b.field_lines.get(key, b.line), f"field '{key}' of '{b.term}' is empty")
                    else:
                        check_text(val, b.field_lines.get(key, b.line))
                for key, ln in b.field_lines.get("__dup__", []):
                    iss.warn(path, ln, f"field '{key}' is written twice in '{b.term}'")
                for kid in b.children:
                    if kid.kind == "para" and FIELD_RE.match(kid.text) and not kid.level:
                        iss.warn(path, kid.line, f"'{kid.text.split('::')[0]}::' looks like a field but is below the "
                                                 f"text of '{b.term}'; fields go on the first lines of a definition")
                walk(b.children)
            elif b.kind == "table":
                cols = player_columns(b)
                header = b.rows[0][1] if b.rows else []
                if not cols and len(header) > 1 and any(P_TOKEN.match(c.strip()) for c in header[1:]):
                    iss.error(path, b.line, "table mixes player codes and other headers; for a player table every "
                                            "header after the first must be a code like 3p, 4-5p, 6+p")
                body = [cells for _, cells in b.rows[1:] if not is_sep_row(cells)]
                if (not cols and not player_rows(b) and body
                        and all(c and re.fullmatch(r"\d+(-\d+|\+)", c[0].strip()) for c in body)):
                    iss.warn(path, b.line, f"first column looks like player counts ('{body[0][0].strip()}'); "
                                           f"write '{body[0][0].strip()}p' so tables are filtered by player count")
                if len({len(c) for _, c in b.rows}) > 1:
                    iss.warn(path, b.line, "table rows have different numbers of cells")
                for ln, cells in b.rows:
                    for j, c in enumerate(cells):
                        check_text(c, ln, allow_block_cond=(j == 0))

    walk(game.blocks)

    # ---- card catalog: a field most cards of a group have, but this one doesn't
    groups: dict[str, list[Block]] = {}
    for c in card_catalog(game.blocks):
        groups.setdefault(c["group"], []).append(c["def"])
    for gname, cards in groups.items():
        if len(cards) < 3:
            continue
        keys = {k for d in cards for k in d.fields}
        for k in sorted(keys):
            have = sum(1 for d in cards if k in d.fields)
            if have * 2 > len(cards):
                for d in cards:
                    if k not in d.fields:
                        iss.warn(path, d.line, f"card '{d.term}' has no '{k}::' field ({have} of {len(cards)} cards "
                                               f"in '{gname or 'cards'}' have one)")

    # ---- references
    known = {norm(c["name"]) for c in components_of(game.blocks)} | set(terms) | bracketed
    if require_defs:      # every component must also be described in the glossary
        reported_defs = set()
        for c in components_of(game.blocks):
            k = norm(c["name"])
            if k not in terms and k not in bracketed and k not in reported_defs:
                reported_defs.add(k)
                iss.warn(path, c["line"], f"component '{c['name']}' has no definition; add '{c['name']}' "
                                          f"then ': …' to the glossary")
    for name, ln in singles:
        if norm(name) in known:
            iss.warn(path, ln, f"'[{name}]' has single brackets; write [[{name}]] to make it a reference")
    seen = set()
    for name, ln, raw in refs:
        if name.startswith("#"):
            if not find_section(game.blocks, name):
                iss.warn(path, ln, f"{raw} matches no section (a heading titled '{name[1:].strip()}', "
                                   f"or a role like #setup)")
            continue
        k = norm(name)
        if k not in known and k not in seen:
            seen.add(k)
            iss.warn(path, ln, f"{raw} matches no component ('- 1x [[{name}]]' in a list) and no definition "
                               f"('{name}' then ': …')")
    return iss


def check_translation(default: Game, tr: Game, vault: Vault, require_defs: bool = False) -> Issues:
    iss = Issues()
    tp = tr.body_path
    for i in check_game(tr, vault, require_defs=require_defs):
        if Path(i.path) == tp and not i.msg.startswith(("cover image",)):
            iss.append(i)
    declared = tr.tr_meta.get("language")
    if declared and declared != tr.language:
        iss.warn(tp, 1, f"language '{declared}' in frontmatter doesn't match the file name ('.{tr.language}.')")
    for k in STRUCTURAL_KEYS:
        if k in tr.tr_meta and str(tr.tr_meta[k]) != str(default.meta.get(k)):
            iss.warn(tp, 1, f"'{k}' differs from the default language ({tr.tr_meta[k]} vs {default.meta.get(k)}); "
                            "leave it out so it is inherited")
    for key, ref in (("variants", default.variants), ("extensions", default.extensions)):
        if not isinstance(tr.tr_meta.get(key), dict):
            continue
        extra = set(tr.tr_meta[key]) - set(ref)
        if extra:
            iss.warn(tp, 1, f"{key} {', '.join(sorted(extra))} not declared in the default language; "
                            "keep the names identical and translate only their descriptions")
    return iss


def rel(p: Path, vault: Vault) -> str:
    try:
        return str(Path(p).resolve().relative_to(vault.root))
    except ValueError:
        return str(p)


def cmd_check(args) -> int:
    if args.stdin:
        if len(args.games) != 1 or not Path(args.games[0]).is_file():
            raise SystemExit("tabula: --stdin needs exactly one .game file (the file being edited)")
        UNSAVED[Path(args.games[0]).resolve()] = sys.stdin.buffer.read().decode("utf-8", errors="replace")
    vault = open_vault(args.vault, args.games[0] if args.games else None)
    paths = [vault.find(g) for g in args.games] if args.games else vault.discover()
    if args.json:
        return check_json(vault, paths, args)
    st = Style(sys.stdout.isatty() and not os.environ.get("NO_COLOR") and not args.no_color)
    te = tw = 0

    def show(i: Issue, indent="  "):
        loc = rel(i.path, vault) + (f":{i.line}" if i.line else "")
        lvl = st.red("error  ") if i.level == "error" else st.yellow("warning")
        print(f"{indent}{lvl}  {loc}  {i.msg}")

    if not args.games:
        for i in vault.issues:
            show(i, "")
        te += sum(i.level == "error" for i in vault.issues)
        tw += sum(i.level == "warning" for i in vault.issues)
    for p in paths:
        game, iss = check_all_languages(vault, p, args.definitions)
        e = sum(i.level == "error" for i in iss)
        w = len(iss) - e
        te, tw = te + e, tw + w
        status = st.green("ok") if not iss else ", ".join(
            x for x in (st.red(f"{e} error(s)") if e else "", st.yellow(f"{w} warning(s)") if w else "") if x)
        langs = f"  [{', '.join(game.languages)}]" if len(game.languages) > 1 else ""
        print(f"{st.bold(game.slug):<30} {status}{st.dim(langs)}")
        for i in iss:
            show(i)
    print(f"\n{len(paths)} game(s), {te} error(s), {tw} warning(s)")
    return 1 if te or (args.strict and tw) else 0


def check_all_languages(vault: Vault, p: Path, definitions: bool) -> tuple[Game, list[Issue]]:
    game = vault.load(p)
    req = bool(definitions or (vault.config.get("check") or {}).get("require_definitions")
               or game.meta.get("require_definitions"))
    iss = list(check_game(game, vault, require_defs=req))
    for lang in game.languages:
        if lang != game.default_language:
            iss += check_translation(game, vault.load(p, lang), vault, require_defs=req)
    iss.sort(key=lambda i: (str(i.path), i.line))
    return game, iss


def check_json(vault: Vault, paths: list[Path], args) -> int:
    """check --json: every issue with an absolute path, for editors and scripts."""
    found = list(vault.issues) if not args.games else []
    files = []
    for p in paths:
        game, iss = check_all_languages(vault, p, args.definitions)
        found += iss
        files += [str(p.parent / (f"{game.slug}.game" if lang == game.default_language else f"{game.slug}.{lang}.game"))
                  for lang in game.languages]
    out = {"vault": str(vault.root), "files": files,
           "issues": [{"path": str(Path(i.path).resolve()), "line": i.line, "level": i.level, "message": i.msg}
                      for i in found]}
    print(json.dumps(out, indent=2))
    errors = sum(i.level == "error" for i in found)
    return 1 if errors or (args.strict and len(found) > errors) else 0


# =========================================================================== html export

UI = {
    "en": {"players": "players", "best": "best with {}", "min": "min", "age": "{}+", "toc": "Contents",
           "showing": "Showing", "base": "base game", "no_variants": "no variants", "all": "every extension and variant",
           "legend": "marks what the enabled extensions and variants add or change",
           "only_with": "only with {}", "by": "Design", "art": "Art", "publisher": "Publisher",
           "exported": "Exported with tabula {} on {}.", "players_n": "{} players",
           "card": "card", "count": "count", "ext": "extension"},
    "fr": {"players": "joueurs", "best": "idéal à {}", "min": "min", "age": "{} ans et +", "toc": "Sommaire",
           "showing": "Affichage", "base": "jeu de base", "no_variants": "sans variante",
           "all": "toutes les extensions et variantes",
           "legend": "signale ce que les extensions et variantes activées ajoutent ou modifient",
           "only_with": "seulement avec {}", "by": "Auteurs", "art": "Illustrations", "publisher": "Éditeur",
           "exported": "Exporté avec tabula {} le {}.", "players_n": "{} joueurs",
           "card": "carte", "count": "nombre", "ext": "extension"},
    "de": {"players": "Spieler", "best": "am besten zu {}", "min": "Min.", "age": "ab {}", "toc": "Inhalt",
           "showing": "Ansicht", "base": "Grundspiel", "no_variants": "ohne Varianten",
           "all": "alle Erweiterungen und Varianten",
           "legend": "markiert, was die aktiven Erweiterungen und Varianten hinzufügen oder ändern",
           "only_with": "nur mit {}", "by": "Autoren", "art": "Illustration", "publisher": "Verlag",
           "exported": "Exportiert mit tabula {} am {}.", "players_n": "{} Spieler",
           "card": "Karte", "count": "Anzahl", "ext": "Erweiterung"},
}

HTML_CSS = r"""
:root{
  --paper:#fbfcfd; --ink:#1d2433; --muted:#5b6475; --rule:#d8dde5; --card:#ffffff; --desk:#eef1f5;
  --term:#0f6e74; --ext:#6b3fa0; --ext-bg:#f4effa; --open:#9a5b00; --open-bg:#fff5e3; --key:#1d2433;
  --serif:"Literata",Georgia,"Iowan Old Style","Palatino Linotype",serif;
  --sans:"Atkinson Hyperlegible",system-ui,"Segoe UI",Roboto,sans-serif;
}
@media (prefers-color-scheme:dark){:root{
  --paper:#15181e; --ink:#e4e7ec; --muted:#9aa3b2; --rule:#2c323d; --card:#1c2028; --desk:#101318;
  --term:#5cc4c9; --ext:#c3a1f0; --ext-bg:#241c33; --open:#f0b55a; --open-bg:#2c2214; --key:#f4f5f7;}}
*{box-sizing:border-box}
html{background:var(--desk)}
body{margin:0;color:var(--ink);background:var(--paper);font:17px/1.62 var(--serif);
  font-feature-settings:"onum","kern";-webkit-text-size-adjust:100%}
.page{display:grid;grid-template-columns:minmax(0,15rem) minmax(0,46rem);gap:3.5rem;justify-content:center;
  max-width:70rem;margin:0 auto;padding:3rem 2rem 5rem}
header.game{grid-column:1/-1;display:grid;grid-template-columns:1fr auto;gap:2rem;align-items:end;
  padding-bottom:1.6rem;border-bottom:2px solid var(--ink)}
header.game h1{font:600 clamp(2.4rem,6vw,3.6rem)/1.02 var(--serif);letter-spacing:-.015em;margin:0 0 .9rem}
.facts{display:flex;flex-wrap:wrap;gap:.45rem;margin:0;padding:0;list-style:none;font:500 .86rem/1 var(--sans)}
.facts li{border:1px solid var(--rule);border-radius:999px;padding:.38rem .7rem;background:var(--card)}
.credits{margin:.9rem 0 0;color:var(--muted);font:.88rem/1.5 var(--sans)}
.credits b{font-weight:600;color:var(--ink)}
.cover{max-width:11rem;max-height:11rem;border-radius:6px;box-shadow:0 1px 0 var(--rule)}
.selection{grid-column:1/-1;margin:-1.5rem 0 0;padding:.75rem 0 0;font:.9rem/1.5 var(--sans);color:var(--muted)}
.selection strong{color:var(--ink);font-weight:600}
nav.toc{position:sticky;top:2rem;align-self:start;font:.92rem/1.45 var(--sans);max-height:calc(100vh - 4rem);overflow:auto}
nav.toc h2{font:600 .95rem/1 var(--sans);margin:0 0 .8rem;color:var(--muted)}
nav.toc ol{list-style:none;margin:0;padding:0}
nav.toc ol ol{padding-left:.9rem;margin:.2rem 0 .4rem;font-size:.88rem}
nav.toc li{margin:.28rem 0}
nav.toc a{color:var(--ink);text-decoration:none;border-left:2px solid transparent;padding-left:.55rem;margin-left:-.6rem;display:block}
nav.toc a:hover,nav.toc a:focus-visible{border-left-color:var(--term);color:var(--term)}
main{min-width:0}
main>*:first-child{margin-top:0}
h2,h3,h4,h5{font-family:var(--serif);line-height:1.2;scroll-margin-top:1.5rem}
main h2{font-size:1.75rem;font-weight:600;margin:3rem 0 1rem;padding-top:.6rem;border-top:1px solid var(--rule)}
main h3{font-size:1.25rem;font-weight:600;margin:2rem 0 .6rem}
main h4,main h5,main h6{font-size:1.05rem;font-weight:600;margin:1.4rem 0 .4rem}
p{margin:0 0 .9rem}
ul,ol{margin:0 0 1rem;padding-left:1.4rem}
li{margin:.25rem 0}
li>ul,li>ol{margin:.25rem 0 .2rem}
ol>li::marker{font:600 .95em var(--sans);color:var(--muted)}
p.key{font-weight:600;padding:.55rem .8rem;border-left:4px solid var(--key);background:var(--card);margin:1rem 0}
p.key::before,li.key::before{content:"★ ";color:var(--open)}
li.key{font-weight:600}
.key-section{border-left:4px solid var(--key);background:var(--card);padding:.2rem 1rem .4rem;margin:1.4rem 0}
.key-section>h2:first-child,.key-section>h3:first-child,.key-section>h4:first-child{margin-top:.6rem}
h2.key::before,h3.key::before,h4.key::before,h5.key::before{content:"★ ";color:var(--open)}
a.ref.section::before{content:"→ ";color:var(--muted)}
aside.note{margin:.8rem 0 1rem;padding:.5rem .9rem;border-left:2px solid var(--rule);color:var(--muted);font-size:.95rem}
aside.note p{margin:0}
a{color:var(--term)}
a.ref{color:var(--term);text-decoration:underline dotted 1.5px;text-underline-offset:.18em}
a.ref:hover{text-decoration-style:solid}
span.ref{border-bottom:1px dotted var(--muted)}
code{font-size:.9em}
pre{background:var(--card);border:1px solid var(--rule);padding:.8rem 1rem;overflow:auto;border-radius:4px}
figure{margin:1.2rem 0}
figure img{max-width:100%;border-radius:4px}
figcaption{font:.85rem var(--sans);color:var(--muted);margin-top:.35rem}
table{border-collapse:collapse;margin:.6rem 0 1.2rem;font:.92rem/1.4 var(--sans)}
th,td{padding:.4rem .8rem .4rem 0;text-align:left;border-bottom:1px solid var(--rule);vertical-align:top}
th{font-weight:600;border-bottom:2px solid var(--ink)}
td:not(:first-child),th:not(:first-child){font-variant-numeric:tabular-nums}
.badge{display:inline-block;font:600 .74rem/1 var(--sans);padding:.22rem .42rem;border-radius:4px;
  vertical-align:.12em;margin-right:.35rem;white-space:nowrap}
.badge.open{color:var(--open);background:var(--open-bg);border:1px solid currentColor}
.badge.ext{color:#fff;background:var(--ext)}
.badge.opt{color:var(--ext);background:var(--ext-bg);border:1px solid currentColor}
@media (prefers-color-scheme:dark){.badge.ext{color:#15181e}}
.from-ext{color:var(--ext)}
p.from-ext,aside.from-ext,table.from-ext{border-left:3px solid var(--ext);padding-left:.8rem}
li.from-ext::marker{color:var(--ext)}
mark.chosen{background:var(--ext-bg);color:var(--ext);padding:0 .15em;border-radius:3px}
.choice{font-family:var(--sans);font-size:.92em;white-space:nowrap}
.choice .alt{border:1px solid var(--open);border-radius:4px;padding:0 .3em;margin:0 .1em;color:var(--ink)}
.choice .alt b{color:var(--open);font-weight:600;margin-right:.25em}
.choice .alt b.opt{color:var(--ext)}
/* glossary entries as playing cards */
.cards{columns:2 17rem;column-gap:.9rem;margin:1rem 0 1.6rem}
hr.end{border:0;border-top:1px solid var(--rule);width:4rem;margin:1.6rem auto}
.card{position:relative;display:inline-block;width:100%;margin:0 0 .9rem;background:var(--card);
  border:1px solid var(--rule);border-radius:11px;padding:.95rem 1.05rem .9rem;font-size:.93rem;line-height:1.5;
  break-inside:avoid;scroll-margin-top:1.5rem}
.card>h3{font:700 1rem/1.25 var(--sans);margin:0 0 .55rem;padding-right:1.6rem}
.card>h3 .badge{float:right;margin:0 -0.3rem 0 .4rem}
.card p:last-child,.card ul:last-child,.card ol:last-child,.card>:last-child{margin-bottom:0}
.card ul,.card ol{padding-left:1.1rem}
.card h4,.card h5{font:600 .93rem/1.3 var(--sans);margin:.9rem 0 .3rem}
.card.ext{border-color:color-mix(in srgb,var(--ext) 45%,var(--rule))}
.card.ext::after{content:"";position:absolute;top:0;right:0;width:1.7rem;height:1.7rem;
  background:linear-gradient(225deg,var(--ext) 50%,transparent 50%);border-top-right-radius:10px}
.card.wide{column-span:all}
table.catalog{width:100%}
table.catalog td:first-child{font-weight:700}
.fields{display:flex;flex-wrap:wrap;gap:.3rem;list-style:none;margin:-.15rem 0 .6rem;padding:0;font:.78rem/1.2 var(--sans)}
.fields li{margin:0;padding:.2rem .45rem;border-radius:4px;background:var(--desk);font-weight:700}
.fields li span{font-weight:400;color:var(--muted)}
.card:target{outline:3px solid var(--term);outline-offset:2px}
.card .from-ext{color:inherit}
footer{grid-column:1/-1;border-top:1px solid var(--rule);padding-top:1rem;color:var(--muted);font:.82rem var(--sans)}
:focus-visible{outline:2px solid var(--term);outline-offset:2px}
@media (max-width:60rem){
  .page{grid-template-columns:minmax(0,1fr);gap:2rem;padding:1.6rem 1.1rem 4rem}
  header.game{grid-template-columns:1fr}
  .cover{max-width:7rem}
  nav.toc{position:static;max-height:none;border:1px solid var(--rule);border-radius:8px;padding:.9rem 1rem;background:var(--card)}
  .selection{margin-top:-1rem}
}
@media print{
  html,body{background:#fff;color:#000}
  :root{--ink:#000;--muted:#444;--rule:#bbb;--card:#fff;--term:#000;--paper:#fff}
  body{font-size:10.5pt}
  .page{display:block;padding:0;max-width:none}
  nav.toc{display:none}
  a.ref{text-decoration:none;border-bottom:.5pt dotted #777}
  main h2{break-after:avoid;margin-top:1.6rem}
  .cards{columns:2;column-gap:6pt}
  .card{border-color:#999;padding:6pt 8pt}
  table,figure,p.key{break-inside:avoid}
}
@media (prefers-reduced-motion:no-preference){html{scroll-behavior:smooth}}
"""


def html_slug(text: str) -> str:
    s = fold(text).replace("'", "")
    return re.sub(r"[^\w]+", "-", s).strip("-") or "section"


class HtmlRenderer:
    def __init__(self, game: Game, blocks: list[Block], ctx: Ctx):
        import html as _html
        self.esc = _html.escape
        self.game, self.blocks, self.ctx = game, blocks, ctx
        self.lang = game.language if game.language in UI else game.language.split("-")[0]
        self.t = UI.get(self.lang, UI["en"])
        self.ids: set[str] = set()
        self.toc: list[tuple[int, str, str]] = []
        # every term of the game, and which ones are actually on this page
        self.entries = {fold(e.name): e for e in lookup_entries(game.blocks)}
        shown = lookup_entries(blocks)
        self.anchor = {fold(e.name): ("t-" if e.kind == "definition" else "c-") + html_slug(e.name) for e in shown}
        self.tip = {k: self._tooltip(e) for k, e in self.entries.items()}
        self.heading_ids: dict[int, str] = {}               # id(heading) -> its HTML id, for [[#Section]] links
        for b in blocks:
            if b.kind == "heading" and not b.reopens:
                self.heading_ids[id(b)] = self.uid(
                    b.roles[0] if b.roles else html_slug(plain(CHOICE_RE.sub("", b.text), ctx)))
        self.catalogs: dict[int, list[dict]] = {}          # id(#cards heading) -> its cards
        for c in card_catalog(blocks):
            if c["catalog"] is not None:
                self.catalogs.setdefault(id(c["catalog"]), []).append(c)

    # ------------------------------------------------------------------ helpers
    def uid(self, base: str) -> str:
        i, cand = 1, base
        while cand in self.ids:
            i += 1
            cand = f"{base}-{i}"
        self.ids.add(cand)
        return cand

    def _tooltip(self, e: "Entry") -> str:
        texts = []
        for b in e.blocks:
            for k in (b.children if b.kind == "def" else [b]):
                if k.text:
                    texts.append(plain(k.text, self.ctx))
        tip = " ".join(texts)
        return tip[:220] + ("…" if len(tip) > 220 else "")

    def data_uri(self, src: str) -> str:
        import base64
        import mimetypes
        if re.match(r"^[a-z]+://", src):
            return src
        p = self.game.base_dir / src
        if not p.exists():
            return src
        mime = mimetypes.guess_type(p.name)[0] or "application/octet-stream"
        return f"data:{mime};base64," + base64.b64encode(p.read_bytes()).decode()

    def label_badges(self, label: str) -> str:
        """Undecided condition codes: player counts in amber, extensions/variants in violet."""
        toks = label.split()
        opts = [t for t in toks if t[:1] in "+-"]
        counts = [t for t in toks if t not in opts]
        out = f'<span class="badge open">{self.esc(" ".join(counts))}</span>' if counts else ""
        return out + (f'<span class="badge opt">{self.esc(" ".join(opts))}</span>' if opts else "")

    def badges(self, b: Block) -> str:
        out = ""
        if lab := open_label(b.cond, self.ctx):
            out += self.label_badges(lab)
        if b.via:
            out += f'<span class="badge ext">+{self.esc(" +".join(b.via))}</span>'
        return out

    # ------------------------------------------------------------------ inline
    def inline(self, text: str) -> str:
        stash: list[str] = []

        def keep(h: str) -> str:
            stash.append(h)
            return f"\x00{len(stash) - 1}\x00"

        text = ESCAPE_RE.sub(lambda m: keep(self.esc(m.group(1))), text)
        text = CHOICE_RE.sub(lambda m: keep(self.choice(m)), text)
        text = REF_RE.sub(lambda m: keep(self.ref(m.group(1).strip(), (m.group(2) or m.group(1).lstrip("#")).strip())), text)
        text = IMAGE_RE.sub(lambda m: keep(f'<img src="{self.esc(self.data_uri(m.group(2)))}" alt="{self.esc(m.group(1))}">'), text)
        text = LINK_RE.sub(lambda m: keep(self.link(m.group(1), m.group(2))), text)
        text = re.sub(r"`([^`]+)`", lambda m: keep(f"<code>{self.esc(m.group(1))}</code>"), text)
        text = self.esc(text, quote=False)
        text = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", text)
        text = re.sub(r"(?<!\w)__(?!\s)(.+?)(?<!\s)__(?!\w)", r"<strong>\1</strong>", text)
        text = re.sub(r"(?<![*\w])\*(?!\s)(.+?)(?<!\s)\*(?![*\w])", r"<em>\1</em>", text)
        text = re.sub(r"(?<!\w)_(?!\s)(.+?)(?<!\s)_(?!\w)", r"<em>\1</em>", text)
        while "\x00" in text:
            text = re.sub(r"\x00(\d+)\x00", lambda m: stash[int(m.group(1))], text)
        return text

    def choice(self, m) -> str:
        branches = parse_choice(m.group(1))
        if branches is None:
            return self.esc(m.group(0))
        ctx = self.ctx
        remaining = [(c, t, any(k == "*" for k, _, _ in c.tokens)) for c, t in branches]
        remaining = [(c, t, star) for c, t, star in remaining if star or cond_ok(c, ctx)]
        concrete = [(c, t) for c, t, star in remaining if not star]
        if concrete:
            c, t = concrete[0]
            if not open_label(c, ctx):
                inner = self.inline(t)
                return f'<mark class="chosen" title="+{self.esc(" +".join(via_of(c, ctx)))}">{inner}</mark>' \
                    if via_of(c, ctx) else inner
            def lab(c, star):
                text = "*" if star else open_label(c, ctx)
                return f'<b class="opt">{self.esc(text)}</b>' if text[:1] in "+-" else f"<b>{self.esc(text)}</b>"
            alts = "".join(f'<span class="alt">{lab(c, star)}{self.inline(t)}</span>' for c, t, star in remaining)
            return f'<span class="choice">{alts}</span>'
        return next((self.inline(t) for _, t, star in remaining if star), "")

    def ref(self, name: str, shown: str) -> str:
        if name.startswith("#"):
            target = find_section(self.blocks, name)
            if target is not None and id(target) in self.heading_ids:
                return f'<a class="ref section" href="#{self.heading_ids[id(target)]}">{self.esc(shown)}</a>'
            return f'<span class="ref section">{self.esc(shown)}</span>'      # not on this page
        k = fold(name)
        tip = self.tip.get(k, "")
        if k in self.anchor:
            return f'<a class="ref" href="#{self.anchor[k]}" title="{self.esc(tip)}">{self.esc(shown)}</a>'
        e = self.entries.get(k)
        if e and e.cond:
            tip = self.t["only_with"].format(e.cond.raw)
        return f'<span class="ref" title="{self.esc(tip)}">{self.esc(shown)}</span>'

    def link(self, label: str, href: str) -> str:
        if href.startswith("game:"):
            href = href[5:] + ".html"
        return f'<a href="{self.esc(href)}">{self.esc(label)}</a>'

    # ------------------------------------------------------------------ blocks
    def render(self, blocks: list[Block], in_card: bool = False) -> str:
        out: list[str] = []
        lists: list[tuple[int, str]] = []          # open lists: (indent, "ul"/"ol")
        counters: dict[int, int] = {}
        k = 0

        def close_lists(to_level: int = -1):
            while lists and lists[-1][0] > to_level:
                out.append(f"</li></{lists.pop()[1]}>")

        while k < len(blocks):
            b = blocks[k]
            nested = b.kind in ("note", "table", "para", "key") and b.level and lists
            if b.kind == "item":
                while lists and lists[-1][0] > b.level:
                    out.append(f"</li></{lists.pop()[1]}>")
                    counters = {l: n for l, n in counters.items() if l <= b.level}
                tag = "ol" if b.ordered else "ul"
                if lists and lists[-1][0] == b.level:
                    out.append("</li>")
                else:
                    out.append(f"<{tag}>")
                    lists.append((b.level, tag))
                attrs, cls = "", []
                if b.ordered:
                    counters[b.level] = counters.get(b.level, b.start - 1) + 1
                    attrs += f' value="{counters[b.level]}"'
                if b.key:
                    cls.append("key")
                if b.tint or b.via:
                    cls.append("from-ext")
                if b.qty and (rm := REF_RE.search(b.text)):
                    a = self.anchor.get(fold(rm.group(1)), "")
                    if a.startswith("c-"):
                        attrs += f' id="{self.uid(a)}"'
                if cls:
                    attrs += f' class="{" ".join(cls)}"'
                out.append(f"<li{attrs}>{self.badges(b)}{self.inline(b.text)}")
                k += 1
                continue
            if not nested:
                close_lists()
                counters = {}
            if b.kind == "heading" and b.key:      # a key section: framed with everything under it
                end = next((j for j in range(k + 1, len(blocks)) if blocks[j].kind == "heading"
                            and blocks[j].level <= b.level
                            and not (blocks[j].reopens and blocks[j].level == b.level)), len(blocks))
                out.append('<section class="key-section">' + self.block(b, in_card)
                           + self.render(blocks[k + 1:end], in_card) + "</section>")
                k = end
                continue
            if b.kind == "def":
                group = []
                while k < len(blocks) and blocks[k].kind == "def":
                    group.append(blocks[k])
                    k += 1
                out.append('<div class="cards">' + "".join(self.card(d) for d in group) + "</div>")
                continue
            out.append(self.block(b, in_card))
            k += 1
        close_lists()
        return "\n".join(out)

    def card(self, d: Block) -> str:
        cid = self.uid(self.anchor.get(fold(d.term), "t-" + html_slug(d.term)))
        from_ext = bool(d.via) or (self.ctx.everything and d.cond is not None and
                                   any(k == "v" and not neg for k, neg, _ in d.cond.tokens))
        cls = "card" + (" ext" if from_ext else "")
        size = sum(len(c.text) for c in d.children) + 120 * sum(1 for c in d.children if c.kind == "heading")
        if size > 900:
            cls += " wide"
        chips = ""
        shown = {k: self.inline(v) for k, v in d.fields.items()}
        shown = {k: v for k, v in shown.items() if re.sub(r"<[^>]+>", "", v).strip()}
        if shown:
            chips = '<ul class="fields">' + "".join(
                f'<li><span>{self.esc(k)}</span> {v}</li>' for k, v in shown.items()) + "</ul>"
        return (f'<article class="{cls}" id="{cid}"><h3>{self.badges(d)}{self.inline(d.term)}</h3>{chips}'
                f'{self.render(d.children, in_card=True)}</article>')

    def block(self, b: Block, in_card: bool) -> str:
        ext = " from-ext" if (b.via or b.tint) else ""
        if b.kind == "heading" and b.reopens:
            return '<hr class="end">'
        if b.kind == "heading":
            level = min(6, b.level + (3 if in_card else 1))
            title = self.inline(b.text)
            hid = self.heading_ids.get(id(b)) or self.uid(
                b.roles[0] if b.roles else html_slug(plain(CHOICE_RE.sub("", b.text), self.ctx)))
            if not in_card and b.level <= 2:
                self.toc.append((b.level, hid, title))
            cls = ' class="key"' if b.key else ""
            head = f'<h{level} id="{hid}"{cls}>{self.badges(b)}{title}</h{level}>'
            if not in_card and id(b) in self.catalogs:
                head += self.catalog_table(self.catalogs[id(b)])
            return head
        if b.kind == "para":
            return f'<p class="{ext.strip()}">{self.badges(b)}{self.inline(b.text)}</p>' if ext else \
                f"<p>{self.badges(b)}{self.inline(b.text)}</p>"
        if b.kind == "key":
            return f'<p class="key{ext}">{self.badges(b)}{self.inline(b.text)}</p>'
        if b.kind == "note":
            return f'<aside class="note{ext}"><p>{self.badges(b)}{self.inline(b.text)}</p></aside>'
        if b.kind == "image":
            return (f'<figure><img src="{self.esc(self.data_uri(b.term))}" alt="{self.esc(b.text)}">'
                    f'<figcaption>{self.inline(b.text)}</figcaption></figure>')
        if b.kind == "code":
            return f"<pre><code>{self.esc(b.text)}</code></pre>"
        if b.kind == "table":
            return self.table(b)
        return ""

    def catalog_table(self, catalog: list[dict]) -> str:
        cols, rows = card_rows(catalog, self.blocks, self.ctx)
        if len(cols) == 1:                      # no counts or fields: the cards themselves are enough
            return ""
        head = "".join(f"<th>{self.esc(self.t.get(c, c))}</th>" for c in cols)
        body = []
        for r in rows:
            cells = []
            for c in cols:
                v = str(r.get(c, ""))
                if c == "card":
                    a = self.anchor.get(fold(v))
                    cells.append(f'<td><a class="ref" href="#{a}">{self.esc(v)}</a></td>' if a else f"<td>{self.esc(v)}</td>")
                elif c == "ext":
                    badge = (self.label_badges(v) if self.ctx.everything
                             else f'<span class="badge ext">{self.esc(v)}</span>') if v else ""
                    cells.append(f"<td>{badge}</td>")
                else:
                    cells.append(f"<td>{self.inline(v)}</td>")
            body.append("<tr>" + "".join(cells) + "</tr>")
        return f'<table class="catalog"><thead><tr>{head}</tr></thead><tbody>{"".join(body)}</tbody></table>'

    def table(self, b: Block) -> str:
        rows = [cells for _, cells in b.rows if not is_sep_row(cells)]
        if not rows:
            return ""

        def cell(c: str, tag: str) -> str:
            pre = ""
            if (lm := re.match(r"\x02(.*?)\x02", c)):
                pre, c = self.label_badges(lm.group(1)), c[lm.end():]
            if (vm := re.match(r"\x01(.*?)\x01", c)):
                pre, c = pre + f'<span class="badge ext">+{self.esc(vm.group(1).replace(",", " +"))}</span>', c[vm.end():]
            return f"<{tag}>{pre}{self.inline(c)}</{tag}>"

        head = "<tr>" + "".join(cell(c, "th") for c in rows[0]) + "</tr>"
        body = "".join("<tr>" + "".join(cell(c, "td") for c in r) + "</tr>" for r in rows[1:])
        return f"<table><thead>{head}</thead><tbody>{body}</tbody></table>"

    # ------------------------------------------------------------------ page
    def page(self, title_suffix: str = "") -> str:
        g, t, esc, ctx = self.game, self.t, self.esc, self.ctx
        body = self.render(self.blocks)          # fills self.toc
        meta = g.meta
        facts = []
        if meta.get("players") is not None:
            facts.append(f"{esc(str(meta['players']).replace('-', '–'))} {t['players']}")
        if meta.get("best_players") is not None:
            facts.append(esc(t["best"].format(meta["best_players"])))
        if meta.get("duration") is not None:
            facts.append(f"{esc(str(meta['duration']).replace('-', '–'))} {t['min']}")
        if meta.get("age") is not None:
            facts.append(esc(t["age"].format(str(meta["age"]).rstrip("+"))))
        credits = []
        for key, label in (("designer", "by"), ("artist", "art"), ("publisher", "publisher")):
            v = meta.get(key)
            if v:
                names = ", ".join(map(str, v)) if isinstance(v, list) else str(v)
                credits.append(f"<b>{t[label]}</b> {esc(names)}")
        cover = ""
        if meta.get("cover") and (g.base_dir / str(meta["cover"])).exists():
            cover = f'<img class="cover" src="{esc(self.data_uri(str(meta["cover"])))}" alt="">'

        sel = []
        if ctx.players is not None:
            sel.append(t["players_n"].format(ctx.players))
        if ctx.everything:
            if g.options:
                sel.append(t["all"])
        else:
            sel += [f"+{v}" for v in sorted(ctx.variants)]
            if g.extensions and not (ctx.variants & {k.lower() for k in g.extensions}):
                sel.append(t["base"])
            if g.variants and not (ctx.variants & {k.lower() for k in g.variants}):
                sel.append(t["no_variants"])
        selection = ""
        if sel:
            selection = f'<p class="selection"><strong>{t["showing"]}:</strong> {esc(", ".join(sel))}'
            if ctx.variants and not ctx.everything:
                selection += f'<br><span class="badge ext">+…</span>{esc(t["legend"])}'
            selection += "</p>"

        toc = ""
        if self.toc:
            items, open_sub = [], False
            for level, hid, title in self.toc:
                title_txt = re.sub(r"<[^>]+>", "", title)
                if level == 1:
                    if open_sub:
                        items.append("</ol></li>")
                        open_sub = False
                    elif items:
                        items.append("</li>")
                    items.append(f'<li><a href="#{hid}">{title_txt}</a>')
                else:
                    if not open_sub:
                        items.append("<ol>")
                        open_sub = True
                    items.append(f'<li><a href="#{hid}">{title_txt}</a></li>')
            items.append("</ol></li>" if open_sub else "</li>")
            toc = f'<nav class="toc" aria-label="{t["toc"]}"><h2>{t["toc"]}</h2><ol>{"".join(items)}</ol></nav>'
        import datetime
        footer = t["exported"].format(__version__, datetime.date.today().isoformat())
        fonts = ('<link rel="preconnect" href="https://fonts.googleapis.com">'
                 '<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Atkinson+Hyperlegible:wght@400;700'
                 '&family=Literata:opsz,wght@7..72,400;7..72,600;7..72,700&display=swap">')
        return f"""<!doctype html>
<html lang="{esc(g.language)}">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{esc(g.title)}{esc(title_suffix)}</title>
{fonts}
<style>{HTML_CSS}</style>
</head>
<body>
<div class="page">
<header class="game"><div><h1>{esc(g.title)}</h1>
<ul class="facts">{"".join(f"<li>{f}</li>" for f in facts)}</ul>
{f'<p class="credits">{" &nbsp; ".join(credits)}</p>' if credits else ""}</div>{cover}</header>
{selection}
{toc}
<main>
{body}
</main>
<footer>{esc(footer)}</footer>
</div>
</body>
</html>
"""


def export_name(game: Game, ctx: Ctx, sections) -> str:
    parts = [game.slug]
    if ctx.players is not None:
        parts.append(f"{ctx.players}p")
    if ctx.everything:
        parts.append("all")
    parts += sorted(ctx.variants)
    if sections:
        parts += [html_slug(s) for s in sections]
    name = "-".join(parts)
    if game.language != game.default_language:
        name += f".{game.language}"
    return name + ".html"


def cmd_export(args) -> int:
    vault = open_vault(args.vault, args.game)
    game = vault.load(vault.find(args.game), args.lang)
    if args.all and (args.ext or args.variant):
        print("tabula: --all already shows every extension and variant; drop either --all or -e/-v", file=sys.stderr)
        return 2
    ctx = Ctx(args.players, {v.lower() for v in (args.variant or []) + (args.ext or [])}, args.all)
    rng = parse_range(game.meta.get("players"))
    if args.players is not None and rng and not in_range(rng, args.players):
        print(f"tabula: {game.title} is for {game.meta.get('players')} players, not {args.players}", file=sys.stderr)
        return 2
    for v in ctx.variants:
        if v not in {k.lower() for k in game.options}:
            print(f"tabula: '{v}' is not a variant or extension of {game.title}", file=sys.stderr)
            return 2
    blocks = filter_blocks(game.blocks, ctx)
    if args.section:
        picked = select_sections(blocks, args.section)
        if not picked:
            print(f"tabula: no section {', '.join(args.section)} in {game.title}; "
                  f"available: {', '.join(section_names(blocks)) or '(none)'}", file=sys.stderr)
            return 2
        blocks = picked
    html_text = HtmlRenderer(game, blocks, ctx).page()
    if args.output == "-":
        sys.stdout.write(html_text)
        return 0
    out = Path(args.output) if args.output else Path.cwd() / export_name(game, ctx, args.section)
    if out.is_dir():
        out = out / export_name(game, ctx, args.section)
    out.write_text(html_text, encoding="utf-8")
    print(f"wrote {out}")
    if any(i.level == "error" for i in game.issues):
        print(f"tabula: this file has errors; run 'tabula check {game.slug}'", file=sys.stderr)
    return 0


# =========================================================================== main

def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="tabula", description="Tabula: board & card game rules in Markdown.")
    ap.add_argument("--version", action="version", version=f"tabula {__version__}")
    ap.add_argument("--vault", help="vault folder (default: $TABULA_VAULT or current directory)")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("list", help="list the games in the vault")
    p.add_argument("-p", "--players", type=int, help="only games playable with N players")
    p.add_argument("-l", "--lang", help="titles in this language where available")
    p.add_argument("--vault", default=argparse.SUPPRESS)
    p.set_defaults(func=cmd_list)

    p = sub.add_parser("show", help="show a game, filtered by player count / variants / language")
    p.add_argument("game")
    p.add_argument("-p", "--players", type=int, help="only what applies to N players")
    p.add_argument("-v", "--variant", action="append", help="turn a variant on (repeatable)")
    p.add_argument("-e", "--ext", action="append", metavar="EXTENSION", help="add an extension (repeatable)")
    p.add_argument("-a", "--all", action="store_true",
                   help="show every extension and variant, marked with badges (default: base game only)")
    p.add_argument("-l", "--lang", help="language (falls back to the default language)")
    p.add_argument("-s", "--section", action="append", metavar="NAME",
                   help="only this section: a role like 'glossary' or 'components', or a heading title (repeatable)")
    p.add_argument("--json", action="store_true", help="print the parsed structure as JSON")
    p.add_argument("--no-color", action="store_true")
    p.add_argument("--vault", default=argparse.SUPPRESS)
    p.set_defaults(func=cmd_show)

    p = sub.add_parser("cards", help="the card catalog: one row per card, with counts and fields")
    p.add_argument("game")
    p.add_argument("-p", "--players", type=int, help="only what applies to N players")
    p.add_argument("-v", "--variant", action="append", help="turn a variant on (repeatable)")
    p.add_argument("-e", "--ext", action="append", metavar="EXTENSION", help="add an extension (repeatable)")
    p.add_argument("-a", "--all", action="store_true", help="every extension and variant")
    p.add_argument("-l", "--lang", help="language")
    p.add_argument("--sort", metavar="COLUMN", help="sort by a column (card, count, or any field), across groups")
    p.add_argument("--json", action="store_true")
    p.add_argument("--no-color", action="store_true")
    p.add_argument("--vault", default=argparse.SUPPRESS)
    p.set_defaults(func=cmd_cards)

    p = sub.add_parser("lookup", help="look up one card, term or section (or list all terms)")
    p.add_argument("game")
    p.add_argument("term", nargs="*", help="term or section to look up; partial names and small typos work")
    p.add_argument("-p", "--players", type=int, help="only what applies to N players")
    p.add_argument("-v", "--variant", action="append", help="turn a variant on (repeatable)")
    p.add_argument("-e", "--ext", action="append", metavar="EXTENSION", help="add an extension (repeatable)")
    p.add_argument("-a", "--all", action="store_true", help="every extension and variant")
    p.add_argument("-l", "--lang", help="language")
    p.add_argument("--max", type=int, default=3, help="show at most this many matches in full (default 3)")
    p.add_argument("--json", action="store_true")
    p.add_argument("--no-color", action="store_true")
    p.add_argument("--vault", default=argparse.SUPPRESS)
    p.set_defaults(func=cmd_lookup)

    p = sub.add_parser("export", help="export a game as a self-contained HTML page")
    p.add_argument("game")
    p.add_argument("-p", "--players", type=int, help="only what applies to N players")
    p.add_argument("-v", "--variant", action="append", help="turn a variant on (repeatable)")
    p.add_argument("-e", "--ext", action="append", metavar="EXTENSION", help="add an extension (repeatable)")
    p.add_argument("-a", "--all", action="store_true", help="every extension and variant, with badges")
    p.add_argument("-s", "--section", action="append", metavar="NAME", help="only some sections (repeatable)")
    p.add_argument("-l", "--lang", help="language")
    p.add_argument("-o", "--output", help="file or folder to write (default: a name like frantic-4p-supercharge.html "
                                          "in the current folder; '-' for standard output)")
    p.add_argument("--vault", default=argparse.SUPPRESS)
    p.set_defaults(func=cmd_export)

    p = sub.add_parser("check", help="find mistakes in game files")
    p.add_argument("games", nargs="*", help="games to check (default: all)")
    p.add_argument("--strict", action="store_true", help="fail on warnings too")
    p.add_argument("--json", action="store_true", help="print the issues as JSON (absolute paths)")
    p.add_argument("--stdin", action="store_true",
                   help="read the one GAME file given from standard input instead of the disk (for editors)")
    p.add_argument("-d", "--definitions", action="store_true",
                   help="every component must also have a glossary definition "
                        "(or set 'check: {require_definitions: true}' in vault.yaml)")
    p.add_argument("--no-color", action="store_true")
    p.add_argument("--vault", default=argparse.SUPPRESS)
    p.set_defaults(func=cmd_check)

    args = ap.parse_args(argv)
    if not hasattr(args, "vault"):
        args.vault = None
    try:
        return args.func(args)
    except BrokenPipeError:
        return 0


if __name__ == "__main__":
    sys.exit(main())
