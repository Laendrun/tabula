"""Totals: a field left empty in a definition is filled in from the cards its list names.

    Attaque
    : avec::
      sans::
      Toutes les cartes de type Attaque
      - [[Attaque 2x]]
      - {+barking} [[Attaque Personnelle 3x]]

`avec` and `sans` of Attaque are the sums of those of the cards listed (only the items, and cards, that
apply with the chosen player count and extensions). Text values that aren't numbers are listed once each.
A listed card can be a group itself.
"""
from __future__ import annotations

import dataclasses

from .blocks import Block
from .syntax import REF_RE, Cond, Ctx, cond_ok, cond_tokens, norm


def members(d: Block) -> list[tuple[list[Cond], str]]:
    """The cards a definition's lists name: [(conditions of the item and its parent items, key)]."""
    out, stack = [], []
    for b in d.children:
        if b.kind != "item":
            continue
        while stack and stack[-1][0] >= b.level:
            stack.pop()
        stack.append((b.level, b.cond))
        m = REF_RE.search(b.text)
        if m and not m.group(1).startswith("#"):
            out.append(([c for _, c in stack if c], norm(m.group(1).split("#")[0])))
    return out


def is_group(d: Block) -> bool:
    return d.kind == "def" and any(v == "" for v in d.fields.values()) and bool(members(d))


def definitions(blocks: list[Block]) -> dict[str, tuple[Block, list[Cond]]]:
    """Every definition, with the conditions of the sections it is in and its own."""
    out, stack = {}, []
    for b in blocks:
        if b.kind == "heading":
            while stack and stack[-1][0] >= b.level:      # as in filter_blocks ("---" headings too)
                stack.pop()
            stack.append((b.level, b.cond))
        elif b.kind == "def":
            out.setdefault(norm(b.term), (b, [c for _, c in stack if c] + ([b.cond] if b.cond else [])))
    return out


def parts(d: Block, key: str, defs: dict, seen: frozenset = frozenset()) -> list[tuple[list[Cond], str]]:
    """[(conditions, value)]: what makes up the total of `key` in the group `d`."""
    out = []
    for conds, target in members(d):
        if target not in defs or target in seen:
            continue
        m, m_conds = defs[target]
        v = m.fields.get(key)
        if v is None:
            continue
        if v == "":
            out += [(conds + m_conds + c, x) for c, x in parts(m, key, defs, seen | {norm(d.term), target})]
        else:
            out.append((conds + m_conds, v))
    return out


def number(v: str) -> float | None:
    try:
        return float(v.replace(",", ".").strip())
    except ValueError:
        return None


def tidy(n: float):
    return int(n) if n == int(n) else n


def unique(tokens) -> list:
    out = []
    for t in tokens:
        if t not in out:
            out.append(t)
    return out


def total(values: list[str]) -> str:
    nums = [number(v) for v in values]
    if values and all(n is not None for n in nums):
        s = sum(nums)
        return str(int(s)) if s == int(s) else f"{s:g}"
    seen = []
    for v in values:
        if v not in seen:
            seen.append(v)
    return ", ".join(seen)


def fill_totals(shown: list[Block], source: list[Block], ctx: Ctx) -> list[Block]:
    """The shown blocks with the empty fields of groups filled in. `source`: the game's blocks, to find the
    listed cards even when they are not shown (`lookup`). Each filled def gets `totals`: {key: [[tokens,
    number]]} for the interactive page (numbers only)."""
    if not any(is_group(b) for b in walk(shown)):
        return shown
    defs = definitions(source)

    def fill(blocks):
        out = []
        for b in blocks:
            if is_group(b):
                fields, totals = dict(b.fields), {}
                for k, v in b.fields.items():
                    if v != "":
                        continue
                    ps = parts(b, k, defs, frozenset({norm(b.term)}))
                    fields[k] = total([x for conds, x in ps if all(cond_ok(c, ctx) for c in conds)])
                    if ps and all(number(x) is not None for _, x in ps):
                        totals[k] = [[unique(t for c in conds for t in cond_tokens(c)), tidy(number(x))]
                                     for conds, x in ps]
                b = dataclasses.replace(b, fields=fields, totals=totals)
            if b.children and b.kind in ("def", "note"):
                b = dataclasses.replace(b, children=fill(b.children))
            out.append(b)
        return out
    return fill(shown)


def walk(blocks):
    for b in blocks:
        yield b
        yield from walk(b.children)


def empty_totals(d: Block, source: list[Block]) -> list[str]:
    """For check: the empty fields of `d` that its list can't fill (no listed card has them)."""
    if not members(d):
        return [k for k, v in d.fields.items() if v == ""]
    defs = definitions(source)
    return [k for k, v in d.fields.items() if v == "" and not parts(d, k, defs, frozenset({norm(d.term)}))]

