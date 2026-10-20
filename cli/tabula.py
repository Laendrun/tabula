#!/usr/bin/env python3
"""tabula — reference CLI for the Tabula game format (spec v0.5).

  tabula list  [-p N] [-l CODE]
  tabula show  GAME [-p N] [-v VARIANT ...] [-l CODE] [--json]
  tabula check [GAME ...] [--strict]

GAME is a slug, a path to a .game file, or a game folder.
The vault is --vault, else $TABULA_VAULT, else the current directory.
"""
from __future__ import annotations

import argparse
import dataclasses
import json
import os
import re
import shutil
import sys
from dataclasses import dataclass, field
from pathlib import Path

try:
    import yaml
except ImportError:  # pragma: no cover
    sys.exit("tabula needs PyYAML:  pip install pyyaml")

__version__ = "0.3.0"

# =========================================================================== syntax

HEADING_RE = re.compile(r"^(#{1,6})\s+(.*?)\s*$")
ITEM_RE = re.compile(r"^(\s*)([-*+]|\d+[.)])\s+(.*)$")
DEF_LINE_RE = re.compile(r"^ {0,3}:(?:\s+(.*)|\s*)$")
FENCE_RE = re.compile(r"^\s*(```|~~~)")
REF_RE = re.compile(r"(?<!\\)\[\[([^\[\]|\n]+?)(?:\|([^\[\]\n]+?))?\]\]")
IMAGE_RE = re.compile(r"(?<!\\)!\[([^\]]*)\]\(([^)\s]+)\)")
LINK_RE = re.compile(r"(?<![!\\\[])\[([^\[\]]+)\]\(([^)\s]+)\)")
COMPONENT_RE = re.compile(r"^(\d+(?:-\d+)?)\s*[x×X]\s+(?=\[\[)")
BLOCK_COND_RE = re.compile(r"^(?<!\\)\{([^{}:|\n]+)\}\s*")
HEADING_COND_RE = re.compile(r"\s+(?<!\\)\{([^{}:|\n]+)\}\s*$")
CHOICE_RE = re.compile(r"(?<!\\)\{([^{}\n]*:[^{}\n]*)\}")
BRACES_RE = re.compile(r"(?<!\\)\{([^{}\n]*)\}")
ESCAPE_RE = re.compile(r"\\([\[\]{}!\\*#])")
LANG_RE = re.compile(r"^[a-z]{2,3}(?:-[A-Za-z0-9]{2,8})?$")

P_TOKEN = re.compile(r"^(!?)(\d+(?:-\d+|\+)?(?:,\d+(?:-\d+|\+)?)*)p$")
V_TOKEN = re.compile(r"^([+-])([A-Za-z0-9][A-Za-z0-9_-]*)$")
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

def read_source(path: Path, issues: Issues) -> tuple[dict, list[tuple[int, str]]]:
    text = path.read_text(encoding="utf-8").lstrip("\ufeff").replace("\r\n", "\n")
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
    via: tuple = ()           # filtered view: the enabled extensions/variants this block comes from
    tint: bool = False        # filtered view: nested under a block that comes from an extension


def is_block_start(t: str) -> bool:
    s = t.lstrip()
    return (not s or bool(HEADING_RE.match(t)) or s.startswith("|") or bool(ITEM_RE.match(t))
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
    i, n = 0, len(lines)
    while i < n:
        ln, t = lines[i]
        if not t.strip():
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
            title, cond = m.group(2), None
            if cm := HEADING_COND_RE.search(title):
                c = parse_cond(cm.group(1))
                if c:
                    cond, title = c, title[: cm.start()]
            blocks.append(Block("heading", title.strip(), ln, level=len(m.group(1)), cond=cond))
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
            kids = parse_blocks(body)
            blocks.append(Block("def", line=ln, term=term, cond=cond, children=kids,
                                items=[["p", k.text, k.line] for k in kids if k.text]))
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
                        if out[j].kind == "heading" and out[j].level <= b.level), len(out))
            if not any(x.kind != "heading" for x in out[k + 1: end]):
                continue
        keep.append(b)
    return keep


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
    def __init__(self, on: bool):
        self.on = on

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


def render_inline(text: str, ctx: Ctx, st: Style) -> str:
    text = resolve_choices(text, ctx, st)
    text = REF_RE.sub(lambda m: st.cyan((m.group(2) or m.group(1)).strip()), text)
    text = IMAGE_RE.sub(lambda m: st.dim(f"[image: {m.group(1) or m.group(2)}]"), text)
    text = LINK_RE.sub(lambda m: f"{m.group(1)} {st.dim('(' + m.group(2) + ')')}", text)
    text = re.sub(r"\*\*(.+?)\*\*", lambda m: st.bold(m.group(1)), text)
    text = re.sub(r"(?<!\w)__(?!\s)(.+?)(?<!\s)__(?!\w)", lambda m: st.bold(m.group(1)), text)
    text = re.sub(r"(?<![*\w])\*(?!\s)(.+?)(?<!\s)\*(?![*\w])", lambda m: st.italic(m.group(1)), text)
    text = re.sub(r"(?<!\w)_(?!\s)(.+?)(?<!\s)_(?!\w)", lambda m: st.italic(m.group(1)), text)
    return ESCAPE_RE.sub(r"\1", text)


def plain(text: str, ctx: Ctx) -> str:
    return render_inline(text, ctx, Style(False))


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
        if b.kind == "heading":
            if out and out[-1] != "":
                out.append("")
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
    d: dict = {"kind": b.kind, "line": b.line}
    if b.cond:
        d["cond"] = b.cond.raw
    if b.via:
        d["from"] = list(b.via)
    if b.kind == "heading":
        d["level"] = b.level
    if b.kind == "table":
        d["player_table"] = player_columns(b) is not None
        d["rows"] = [[plain(re.sub(r"\x01.*?\x01", "", c), ctx) for c in cells] for _, cells in b.rows if not is_sep_row(cells)]
    elif b.kind == "def":
        d["term"] = b.term
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
    if args.json:
        print(json.dumps({
            "slug": game.slug, "title": game.title, "path": str(game.body_path or game.path),
            "language": game.language, "languages": game.languages, "meta": game.meta,
            "filters": {"players": ctx.players, "options": sorted(ctx.variants), "all": ctx.everything},
            "components": [{k: v for k, v in c.items() if k != "line"} for c in components_of(blocks)],
            "glossary": [{"term": b.term, "definition": [plain(k.text, ctx) for k in b.children if k.text]}
                         for b in blocks if b.kind == "def"],
            "key_rules": [plain(b.text, ctx) for b in blocks if b.kind == "key" or (b.kind == "item" and b.key)],
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
        if re.search(r"(?<!\\)\[\[(?![^\]]*\]\])", REF_RE.sub("", rest)):
            iss.error(path, ln, "unclosed '[[' reference")
        for m in IMAGE_RE.finditer(rest):
            src = m.group(2)
            if not re.match(r"^[a-z]+://", src) and not (game.base_dir / src).exists():
                iss.error(path, ln, f"image not found: {src}")

    terms: dict[str, tuple[int, str]] = {}
    bracketed: set[str] = set()      # terms written as [[Term]]: reported once, not at every reference

    def walk(blocks: list[Block]):
        for b in blocks:
            if b.cond:
                check_cond(b.cond, b.line)
            if b.kind == "heading":
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
                if not b.children:
                    iss.warn(path, b.line, f"definition of '{b.term}' is empty")
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
    vault = open_vault(args.vault, args.games[0] if args.games else None)
    paths = [vault.find(g) for g in args.games] if args.games else vault.discover()
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
        game = vault.load(p)
        req = bool(args.definitions or (vault.config.get("check") or {}).get("require_definitions")
                   or game.meta.get("require_definitions"))
        iss = list(check_game(game, vault, require_defs=req))
        for lang in game.languages:
            if lang != game.default_language:
                iss += check_translation(game, vault.load(p, lang), vault, require_defs=req)
        iss.sort(key=lambda i: (str(i.path), i.line))
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
    p.add_argument("--json", action="store_true", help="print the parsed structure as JSON")
    p.add_argument("--no-color", action="store_true")
    p.add_argument("--vault", default=argparse.SUPPRESS)
    p.set_defaults(func=cmd_show)

    p = sub.add_parser("check", help="find mistakes in game files")
    p.add_argument("games", nargs="*", help="games to check (default: all)")
    p.add_argument("--strict", action="store_true", help="fail on warnings too")
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
