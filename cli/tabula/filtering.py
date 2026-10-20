"""Keeping only what applies: player count, variants, extensions, sections."""
from __future__ import annotations

import dataclasses
import re

from .syntax import (
    BLOCK_COND_RE, CHOICE_RE, Ctx, cond_ok, in_range, norm, open_label, parse_cond, via_of,
)
from .blocks import Block, player_columns, player_rows
from .terminal import plain

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
