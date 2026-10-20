"""tabula — reference CLI for the Tabula game format (spec v0.7).

  tabula list  [-p N] [-l CODE]
  tabula show  GAME [-p N] [-v VARIANT ...] [-l CODE] [-k] [--json]
  tabula export GAME [-p N] [-e EXT] [-v VARIANT] [--all] [-s SECTION] [-k] [-o FILE]
  tabula cards GAME [-p N] [-e EXT] [--all] [--sort COLUMN]
  tabula lookup GAME [TERM] [-p N] [-e EXT] [-v VARIANT] [--all]
  tabula check [GAME ...] [--strict] [-d]

GAME is a slug, a path to a .game file, or a game folder.
The vault is --vault, else $TABULA_VAULT, else the current directory.
"""
from __future__ import annotations

import argparse

from ._version import __version__
from .show import cmd_list, cmd_show
from .lookup import cmd_lookup
from .cards import cmd_cards
from .check import cmd_check
from .export import cmd_export

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
    p.add_argument("-s", "--section", action="append", metavar="NAME",
                   help="only this section: a role like 'glossary' or 'components', or a heading title (repeatable)")
    p.add_argument("-k", "--key", action="store_true",
                   help="only the key rules ('! …') and key sections ('## ! Title'): a cheat sheet")
    p.add_argument("--json", action="store_true", help="print the parsed structure as JSON")
    p.add_argument("--no-color", action="store_true")
    p.add_argument("--vault", default=argparse.SUPPRESS)
    p.set_defaults(func=cmd_show)

    p = sub.add_parser("cards", help="the card catalog: one row per card, with counts and fields")
    p.add_argument("game")
    p.add_argument("-p", "--players", type=int, help="only what applies to N players")
    p.add_argument("-v", "--variant", action="append", help="turn a variant on (repeatable)")
    p.add_argument("-e", "--ext", action="append", metavar="EXTENSION", help="add an extension (repeatable)")
    p.add_argument("-a", "--all", action="store_true", help="every extension and variant")
    p.add_argument("-l", "--lang", help="language")
    p.add_argument("--sort", metavar="COLUMN", help="sort by a column (card, count, or any field), across groups")
    p.add_argument("--json", action="store_true")
    p.add_argument("--no-color", action="store_true")
    p.add_argument("--vault", default=argparse.SUPPRESS)
    p.set_defaults(func=cmd_cards)

    p = sub.add_parser("lookup", help="look up one card, term or section (or list all terms)")
    p.add_argument("game")
    p.add_argument("term", nargs="*", help="term or section to look up; partial names and small typos work")
    p.add_argument("-p", "--players", type=int, help="only what applies to N players")
    p.add_argument("-v", "--variant", action="append", help="turn a variant on (repeatable)")
    p.add_argument("-e", "--ext", action="append", metavar="EXTENSION", help="add an extension (repeatable)")
    p.add_argument("-a", "--all", action="store_true", help="every extension and variant")
    p.add_argument("-l", "--lang", help="language")
    p.add_argument("--max", type=int, default=3, help="show at most this many matches in full (default 3)")
    p.add_argument("--json", action="store_true")
    p.add_argument("--no-color", action="store_true")
    p.add_argument("--vault", default=argparse.SUPPRESS)
    p.set_defaults(func=cmd_lookup)

    p = sub.add_parser("export", help="export a game as a self-contained HTML page")
    p.add_argument("game")
    p.add_argument("-p", "--players", type=int, help="only what applies to N players")
    p.add_argument("-v", "--variant", action="append", help="turn a variant on (repeatable)")
    p.add_argument("-e", "--ext", action="append", metavar="EXTENSION", help="add an extension (repeatable)")
    p.add_argument("-a", "--all", action="store_true", help="every extension and variant, with badges")
    p.add_argument("-s", "--section", action="append", metavar="NAME", help="only some sections (repeatable)")
    p.add_argument("-k", "--key", action="store_true", help="only the key rules and key sections: a cheat sheet")
    p.add_argument("-l", "--lang", help="language")
    p.add_argument("-o", "--output", help="file or folder to write (default: a name like frantic-4p-supercharge.html "
                                          "in the current folder; '-' for standard output)")
    p.add_argument("--vault", default=argparse.SUPPRESS)
    p.set_defaults(func=cmd_export)

    p = sub.add_parser("check", help="find mistakes in game files")
    p.add_argument("games", nargs="*", help="games to check (default: all)")
    p.add_argument("--strict", action="store_true", help="fail on warnings too")
    p.add_argument("--json", action="store_true", help="print the issues as JSON (absolute paths)")
    p.add_argument("--stdin", action="store_true",
                   help="read the one GAME file given from standard input instead of the disk (for editors)")
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
