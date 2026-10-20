"""`tabula list` and `tabula show`."""
from __future__ import annotations

import json
import os
import shutil
import sys

from .syntax import Ctx, in_range, parse_range
from .blocks import components_of
from .filtering import filter_blocks, section_names, select_key, select_sections
from .vault import open_vault
from .terminal import Style, block_json, plain, render_blocks

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
    if args.key:
        blocks = select_key(blocks)
        if not blocks:
            print(f"tabula: no key rules in {game.title} (mark them with '! ' or '## ! Title')", file=sys.stderr)
            return 1
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
    f = ["key rules"] if args.key else []
    f += [f"{ctx.players} players"] if ctx.players is not None else []
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
