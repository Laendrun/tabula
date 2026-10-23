"""The Tabula syntax: regular expressions, names, player ranges and conditions."""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field

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


KNOWN_ROLES = ("components", "goal", "setup", "play", "turn", "scoring", "end", "glossary", "cards", "events",
               "variants", "notes", "faq")


CONDISH_RE = re.compile(r"(\d\s*p\b|^\s*[+!-]\w|\bp\s*=|^\s*\*\s*$)")


def norm(name: str) -> str:
    """Case- and plural-insensitive key: 'Cartes Chaussettes' == 'carte chaussette'."""
    words = []
    for w in name.lower().split():
        if len(w) > 2 and w[-1] in "sx" and not w.endswith("ss"):   # dés = dé, cartes = carte
            w = w[:-1]
        words.append(w)
    return " ".join(words)


def split_lang(stem: str) -> tuple[str, str | None]:
    if "." in stem:
        base, lang = stem.rsplit(".", 1)
        if LANG_RE.match(lang):
            return base, lang
    return stem, None


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


def split_bars(s: str) -> list[str]:
    """Split at "|", except inside [[a|b]], an inline choice {2p: a | *: b} (in a table cell) and an escaped
    \\| (kept as written)."""
    parts, cur, depth, i = [], "", 0, 0
    while i < len(s):
        if s.startswith("[[", i):
            depth, cur, i = depth + 1, cur + "[[", i + 2
        elif s.startswith("]]", i) and depth:
            depth, cur, i = depth - 1, cur + "]]", i + 2
        elif s[i] == "{" and "}" in s[i:]:
            depth, cur, i = depth + 1, cur + "{", i + 1
        elif s[i] == "}" and depth:
            depth, cur, i = depth - 1, cur + "}", i + 1
        elif s[i] == "\\" and i + 1 < len(s):
            cur, i = cur + s[i:i + 2], i + 2
        elif s[i] == "|" and not depth:
            parts.append(cur)
            cur, i = "", i + 1
        else:
            cur, i = cur + s[i], i + 1
    return parts + [cur]


def parse_choice(body: str):
    """'3p: 17 | 4p: 13 | *: 10' -> [(Cond, text)] or None if not a valid choice."""
    branches = []
    for part in split_bars(body):
        if ":" not in part:
            return None
        c, text = part.split(":", 1)
        cond = parse_cond(c)
        if cond is None:
            return None
        branches.append((cond, text.strip() if text.strip() else text.rstrip()))
    return branches or None


def via_of(cond: Cond | None, ctx: Ctx) -> tuple:
    """Enabled extensions/variants that a matching condition asks for (used for highlighting)."""
    if cond is None or ctx.everything:
        return ()
    return tuple(v for k, neg, v in cond.tokens if k == "v" and not neg and v in ctx.variants)


def fold(text: str) -> str:
    """Search key: case, accents and plurals ignored ('Événements' == 'evenement')."""
    text = unicodedata.normalize("NFKD", text)
    text = "".join(c for c in text if not unicodedata.combining(c))
    return norm(re.sub(r"[^\w\s'-]", " ", text))


def json_range(rng) -> list:
    """[(2, 4), (6, inf)] -> [[2, 4], [6, null]] for the page's script."""
    return [[lo, None if hi == float("inf") else hi] for lo, hi in rng]


def cond_tokens(cond: Cond | None) -> list:
    """A condition as JSON-ready tokens: ["p", negated, ranges] and ["v", negated, name] ("*" is left out)."""
    out = []
    for kind, neg, val in (cond.tokens if cond else []):
        if kind == "p":
            out.append(["p", neg, json_range(val)])
        elif kind == "v":
            out.append(["v", neg, val])
    return out
