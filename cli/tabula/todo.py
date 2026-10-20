"""`tabula todo`: the reminders left in game files as <!-- TODO: … --> comments."""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

from .fragments import SHARED_DIR, fragment_files
from .source import find_todos
from .syntax import split_lang
from .terminal import Style
from .vault import open_vault


def game_files(path: Path, slug: str, languages: list[str], default: str) -> list[Path]:
    return [path.parent / (f"{slug}.game" if lang == default else f"{slug}.{lang}.game") for lang in languages]


def cmd_todo(args) -> int:
    vault = open_vault(args.vault, args.games[0] if args.games else None)
    paths = [vault.find(g) for g in args.games] if args.games else vault.discover() + [
        f for f in fragment_files(vault.root) if split_lang(f.stem)[1] is None]
    found = []                       # (game, file, line, text)
    for p in paths:
        game = vault.load(p)
        for f in game_files(p, game.slug, game.languages, game.default_language):
            found += [(game, f, ln, text) for ln, text in find_todos(f)]
    if args.json:
        print(json.dumps([{"game": g.slug, "path": str(f.resolve()), "line": ln, "text": t} for g, f, ln, t in found],
                         indent=2, ensure_ascii=False))
        return 0
    if not found:
        print("no TODOs" + (f" in {', '.join(args.games)}" if args.games else ""))
        return 0
    st = Style(sys.stdout.isatty() and not os.environ.get("NO_COLOR") and not args.no_color)
    current = None
    for g, f, ln, text in found:
        if g.slug != current:
            if current is not None:
                print()
            label = f"{SHARED_DIR}/{g.slug}" if g.path.parent.name == SHARED_DIR else g.slug
            print(st.bold(g.title) + st.dim(f"  ({label})"))
            current = g.slug
        print(f"  {st.dim(f'{f.name}:{ln}')}  {text}")
    games = len({g.path for g, *_ in found})
    print(f"\n{len(found)} TODO(s) in {games} file(s)" if any(g.path.parent.name == SHARED_DIR for g, *_ in found)
          else f"\n{len(found)} TODO(s) in {games} game(s)")
    return 0
