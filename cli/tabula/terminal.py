"""Rendering for the terminal (and plain text / JSON)."""
from __future__ import annotations

import re

from .syntax import (
    CHOICE_RE, Ctx, ESCAPE_RE, IMAGE_RE, LINK_RE, REF_RE, cond_ok, fold, open_label,
    parse_choice, via_of,
)
from .blocks import Block, callout_family, callout_title, is_sep_row, player_columns

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
    text = IMAGE_RE.sub(lambda m: m.group(1)[4:] if m.group(1).startswith("sym:")      # a symbol: its text
                        else st.dim(f"[image: {m.group(1) or m.group(2)}]"), text)
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
        if b.kind == "heading" and b.reopens and b.quiet:
            continue
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
        elif b.kind == "note" and b.callout:
            if b.level == 0 or not counters:
                gap()
            pad = " " * (b.level + (2 if b.level else 0))
            fam = callout_family(b.callout)
            icon, color = {"example": ("◆", st.magenta), "warning": ("⚠", st.yellow), "tip": ("✦", st.green),
                           "info": ("ℹ", st.cyan), "question": ("?", st.cyan), "note": ("▪", st.dim)}[fam]
            bar = color("┃ ")
            out.append(pad + bar + badge(b) + color(st.bold(f"{icon} {render_inline(callout_title(b), ctx, st)}")))
            if txt:
                out += wrap(txt, width, pad + bar)
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
                one_line = "   ".join(f"{st.dim(k + ':')} {v}" for k, v in shown.items())
                if vlen(one_line) + 4 <= width:
                    out.append("    " + one_line)
                else:                    # long values: one field per line, continued under its value
                    for k, v in shown.items():
                        out += wrap(f"{st.dim(k + ':')} {v}", width, "    ", " " * (6 + len(k)))
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
        if b.callout:
            d["callout"] = b.callout
            d["title"] = plain(callout_title(b), ctx)
        if b.kind == "image":
            d["src"] = b.term
        if b.kind == "item":
            d.update(ordered=b.ordered, indent=b.level, key=b.key)
            if b.qty:
                d["component"] = True
    return d
