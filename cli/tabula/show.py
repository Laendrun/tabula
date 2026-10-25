"""`tabula list` and `tabula show`."""
from __future__ import annotations

import json
import os
import shutil
import sys

from .syntax import Ctx, in_range, parse_range
from .blocks import components_of
from .filtering import filter_blocks, section_names, select_key, select_sections, select_summary, select_turn
from .vault import open_vault
from .fields import GAME_KEYS, extra_fields, year
from .options import OPTION_KEYS, apply_options, names, option_info, players_note, players_range
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
    if year(meta):
        bits.append(year(meta))
    return " · ".join(bits)


def option_label(game, name: str) -> str:
    """'pandora (2019, 2-10p, needs troublemaker, Box: blue)' for the terminal."""
    d = option_info(game, name)
    bits = ([year(d)] if year(d) else []) + ([f"{d['players']}p"] if d.get("players") else []) + \
           ([f"needs {', '.join(names(d['needs']))}"] if d.get("needs") else []) + \
           ([f"not with {', '.join(names(d['excludes']))}"] if d.get("excludes") else [])
    bits += [f"{k}: {v}" for k, v in extra_fields(d, OPTION_KEYS)]
    return f"{name} ({', '.join(bits)})" if bits else name


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
    declared = game.variants
    for v in ctx.variants:
        if v not in {k.lower() for k in game.options}:
            print(f"tabula: '{v}' is not a variant or extension of {game.title}; "
                  f"variants: {', '.join(game.variants) or '(none)'}; extensions: {', '.join(game.extensions) or '(none)'}",
                  file=sys.stderr)
            return 2
    if (code := apply_options(game, ctx, args.players)) is not None:
        return code

    blocks = filter_blocks(game.blocks, ctx)
    if args.section:
        picked = select_sections(blocks, args.section)
        if not picked:
            avail = section_names(blocks)
            print(f"tabula: no section {', '.join(args.section)} in {game.title}; "
                  f"available: {', '.join(avail) or '(none)'}", file=sys.stderr)
            return 2
        blocks = picked
    if args.summary:
        blocks = select_summary(blocks, turn=args.turn)
        if not blocks:
            print(f"tabula: no rules summary in {game.title} (give the section that sums up the rules the role "
                  f"#summary: '## En bref {{#summary}}')", file=sys.stderr)
            return 1
    elif args.turn:
        blocks = select_turn(blocks)
        if not blocks:
            print(f"tabula: no turn summary in {game.title} (give the section that describes a turn the role "
                  f"#turn: '## À votre tour {{#turn}}')", file=sys.stderr)
            return 1
    elif args.key:
        blocks = select_key(blocks)
        if not blocks:
            print(f"tabula: no key rules in {game.title} (mark them with '! ' or '## ! Title')", file=sys.stderr)
            return 1
    if args.json:
        print(json.dumps({
            "slug": game.slug, "title": game.title, "path": str(game.body_path or game.path),
            "language": game.language, "languages": game.languages, "meta": game.meta,
            "cover": str(game.cover) if game.cover and game.cover.is_file() else None,
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
    if own := extra_fields(game.meta, GAME_KEYS, game.language):
        out.append(st.dim(" · ".join(f"{k}: {v}" for k, v in own)))
    f = ["rules summary"] if args.summary else ["turn summary"] if args.turn else ["key rules"] if args.key else []
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
        info.append("extensions: " + ", ".join(option_label(game, e) for e in game.extensions) + " (-e NAME)")
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
    if getattr(args, "json", False):
        from .sheet import sheets_of
        out = []
        for p in vault.discover():
            g = vault.load(p, args.lang)
            if args.players is not None and not in_range(players_range(g, everything=True) or [], args.players):
                continue
            out.append({"slug": g.slug, "title": g.title, "path": str(p), "players": g.meta.get("players"),
                        "players_note": players_note(g), "duration": g.meta.get("duration"),
                        "year": g.meta.get("year"),
                        "location": g.meta.get("location"), "language": g.default_language,
                        "translations": {l: str(p.parent / f"{g.slug}.{l}.game") for l in g.languages
                                         if l != g.default_language},
                        "sheets": [str(s) for s in sheets_of(p, vault.root)],
                        "cover": str(g.cover) if g.cover and g.cover.is_file() else None})
        print(json.dumps({"vault": str(vault.root), "name": str(vault.config.get("name") or vault.root.name),
                          "games": out}, indent=2, ensure_ascii=False, default=str))
        return 0
    rows = []
    for p in vault.discover():
        g = vault.load(p, args.lang)
        rng = parse_range(g.meta.get("players"))
        full = players_range(g, everything=True)
        if args.players is not None and not (full and in_range(full, args.players)):
            continue
        players = str(g.meta.get("players", "?"))
        if args.players is not None and not (rng and in_range(rng, args.players)):
            players += " (" + ", ".join(f"+{o}" for o in g.options if in_range(
                players_range(g, {o.lower()}) or [], args.players)) + ")"     # only with an extension
        elif note := players_note(g):
            players += f" ({note})"
        rows.append([g.slug, g.title, players, str(g.meta.get("duration", "")),
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
