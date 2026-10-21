"""tabula — reference CLI for the Tabula game format (spec v0.8).

  tabula list  [-p N] [-l CODE]
  tabula show  GAME [-p N] [-v VARIANT ...] [-l CODE] [-k] [--json]
  tabula export GAME [-p N] [-e EXT] [-v VARIANT] [--all] [-s SECTION] [-k] [-o FILE]
  tabula cards GAME [-p N] [-e EXT] [--all] [--sort COLUMN]
  tabula lookup GAME [TERM] [-p N] [-e EXT] [-v VARIANT] [--all]
  tabula book [GAME ...] [-p N] [-e EXT] [-k] [-l CODE] [-o FILE]
  tabula site [-o FOLDER]
  tabula new  SLUG | bgg ID [SLUG]
  tabula todo [GAME ...]
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
from .site import cmd_site
from .todo import cmd_todo
from .new import cmd_new
from .book import cmd_book

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

    p = sub.add_parser("book", help="games as an EPUB book for e-readers, phones and tablets (default: the whole vault)")
    p.add_argument("games", nargs="*", help="games to include (default: all)")
    p.add_argument("-p", "--players", type=int, help="only what applies to N players (games not for N are left out)")
    p.add_argument("-v", "--variant", action="append", help="only this variant (repeatable)")
    p.add_argument("-e", "--ext", action="append", metavar="EXTENSION", help="only this extension (repeatable)")
    p.add_argument("-a", "--all", action="store_true", help="every extension and variant, marked (the default)")
    p.add_argument("-k", "--key", action="store_true", help="only the key rules: a cheat-sheet book")
    p.add_argument("-l", "--lang", help="language (default: the vault's; games without it stay in theirs)")
    p.add_argument("-t", "--title", help="the book's title (default: the vault's name, or the game's title)")
    p.add_argument("-o", "--output", help="file or folder to write (default: <vault-name>.epub here)")
    p.add_argument("--vault", default=argparse.SUPPRESS)
    p.set_defaults(func=cmd_book)

    p = sub.add_parser("site", help="the whole vault as a small website: an index page and a page per game")
    p.add_argument("-o", "--output", metavar="FOLDER",
                   help="folder to write (default: ./site); replaced on every run, but only if tabula made it")
    p.add_argument("--vault", default=argparse.SUPPRESS)
    p.set_defaults(func=cmd_site)

    p = sub.add_parser(
        "new", help="start a game file: blank, or filled from BoardGameGeek",
        usage="tabula new SLUG [-t TITLE] [-p PLAYERS] [-l LANG]\n"
              "       tabula new bgg ID [SLUG] [-t TITLE] [--no-cover]\n"
              "       tabula new bgg NAME          (lists the matching games and their IDs)",
        description="tabula new SLUG writes a blank game (works offline).\n"
                    "tabula new bgg ID fills the frontmatter from BoardGameGeek: title, players, duration, age,\n"
                    "year, designers, artists, publisher and the box image.\n\n"
                    "BoardGameGeek needs a token: register an application at https://boardgamegeek.com/applications,\n"
                    "then set the BGG_TOKEN environment variable (or pass --token).",
        formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("what", nargs="+", help=argparse.SUPPRESS)
    p.add_argument("-t", "--title", help="title (default: from the slug, or BoardGameGeek's name)")
    p.add_argument("-p", "--players", help="player count, e.g. 2-4")
    p.add_argument("-l", "--lang", help="language of the game (default: the vault's)")
    p.add_argument("--token", help="BoardGameGeek token (default: $BGG_TOKEN)")
    p.add_argument("--no-cover", action="store_true", help="don't download the box image from BoardGameGeek")
    p.add_argument("--force", action="store_true", help="replace an existing game file")
    p.add_argument("--vault", default=argparse.SUPPRESS)
    p.set_defaults(func=cmd_new)

    p = sub.add_parser("todo", help="list the <!-- TODO: … --> reminders left in game files")
    p.add_argument("games", nargs="*", help="games to look in (default: all)")
    p.add_argument("--json", action="store_true")
    p.add_argument("--no-color", action="store_true")
    p.add_argument("--vault", default=argparse.SUPPRESS)
    p.set_defaults(func=cmd_todo)

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
