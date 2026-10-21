"""The card catalog and `tabula cards`."""
from __future__ import annotations

import json
import os
import re
import shutil
import sys

from .syntax import Ctx, fold
from .blocks import Block, components_of
from .filtering import filter_blocks
from .vault import open_vault
from .terminal import Style, plain, render_inline, vlen, wrap

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
        keys += [k for k in c["def"].fields if k not in keys and k not in ("count", "image")]   # pictures: drawn
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


def fit_widths(widths: list[int], total: int, gap: int = 2, least: int = 16) -> list[int]:
    """Column widths that fit in `total` characters: the widest columns are narrowed first (their text wraps)."""
    widths = list(widths)
    while sum(widths) + gap * (len(widths) - 1) > total:
        j = max(range(len(widths)), key=lambda k: widths[k])
        if widths[j] <= least:
            break                                 # can't narrow further: let the terminal wrap the rest
        widths[j] -= 1
    return widths


def table_row(cells: list[str], widths: list[int], gap: int = 2) -> list[str]:
    """One table row as one or more lines, each cell wrapped to its column."""
    wrapped = [wrap(c, w) if vlen(c) > w else [c] for c, w in zip(cells, widths)]
    lines = []
    for i in range(max(len(w) for w in wrapped)):
        parts = [(w[i] if i < len(w) else "") for w in wrapped]
        lines.append((" " * gap).join(p + " " * (widths[j] - vlen(p)) for j, p in enumerate(parts)).rstrip())
    return lines


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
    term_width = shutil.get_terminal_size((100, 20)).columns
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
        widths = fit_widths([max(vlen(row[j]) for row in table) for j in range(len(cols))], term_width)
        if out:
            out.append("")
        if g:
            out.append(st.bold(st.yellow(render_inline(g, ctx, st))))
        out += [st.dim(line) for line in table_row(table[0], widths)]
        for row in table[1:]:
            out += table_row(row, widths)
    total = len(rows)
    out += ["", st.dim(f"{total} card{'s' if total != 1 else ''}" + (" · sorted by " + args.sort if args.sort else ""))]
    print("\n".join(out))
    return 0
