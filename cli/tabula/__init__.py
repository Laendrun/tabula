"""tabula: reference tools for the Tabula game format (board and card game rules in Markdown).

The command line lives in `tabula.cli`; the main building blocks are re-exported here.
"""
from ._version import __version__
from .blocks import Block, components_of, parse_blocks
from .cards import card_catalog
from .check import check_game, check_translation
from .cli import main
from .filtering import filter_blocks, select_sections
from .lookup import lookup_entries
from .syntax import (
    Ctx, cond_ok, fold, norm, parse_attrs, parse_choice, parse_cond, parse_range, split_lang,
)
from .vault import Game, Vault, open_vault

__all__ = [
    "__version__", "Block", "Ctx", "Game", "Vault", "card_catalog", "check_game", "check_translation",
    "components_of", "filter_blocks", "fold", "lookup_entries", "main", "norm", "open_vault",
    "parse_blocks", "parse_cond", "select_sections", "cond_ok", "parse_attrs", "parse_choice", "parse_range",
    "split_lang",
]
