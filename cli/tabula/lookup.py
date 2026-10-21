"""`tabula lookup`: one term, section or component, for use at the table."""
from __future__ import annotations

import difflib
import json
import os
import shutil
import sys
from dataclasses import dataclass

from .syntax import COMPONENT_RE, Cond, Ctx, REF_RE, cond_ok, fold
from .blocks import Block
from .filtering import filter_blocks, select_sections
from .vault import open_vault
from .options import apply_options
from .terminal import Style, block_json, render_blocks, wrap

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
    if (code := apply_options(game, ctx, args.players)) is not None:
        return code
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
