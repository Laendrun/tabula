"""Your own properties: frontmatter keys (and extension or variant details) the spec doesn't define.

Only the keys of the spec do something. Any other key is kept and shown as it is, as "Label: value", in the
header of the exported page, the book and `tabula show`:

    ---
    title: Frantic
    players: 2-8
    year: 2018
    series: Rulefactory      # your own: shown as "Series: Rulefactory"
    bought_at: Spiel 2019    # "Bought at: Spiel 2019"
    ---
"""
from __future__ import annotations

import datetime

# the frontmatter keys of the spec (SPEC.md 3.1)
GAME_KEYS = ("title", "players", "best_players", "duration", "age", "type", "tags", "designer", "artist",
             "publisher", "year", "language", "variants", "extensions", "location", "cover", "links",
             "source", "require_definitions", "unused_definitions", "spelling", "words", "values", "symbols")

YES_NO = {"en": ("yes", "no"), "fr": ("oui", "non"), "de": ("ja", "nein")}


def label(key) -> str:
    """'bought_at' → 'Bought at'; a key with capitals is kept as written ('BGG rank')."""
    s = str(key).replace("_", " ").strip()
    return s[:1].upper() + s[1:] if s == s.lower() else s


def text(value, lang: str = "en") -> str:
    """A value as one line: lists joined with commas, mappings as 'key: value; …'."""
    if isinstance(value, bool):
        yes, no = YES_NO.get(lang, YES_NO["en"])
        return yes if value else no
    if isinstance(value, (datetime.date, datetime.datetime)):
        return value.isoformat()
    if isinstance(value, dict):
        return "; ".join(f"{label(k)}: {text(v, lang)}" for k, v in value.items() if not empty(v))
    if isinstance(value, (list, tuple)):
        return ", ".join(text(v, lang) for v in value if not empty(v))
    return str(value).strip()


def empty(value) -> bool:
    return value is None or (isinstance(value, (str, list, tuple, dict)) and not value)


def extra_fields(d, known=GAME_KEYS, lang: str = "en") -> list[tuple[str, str]]:
    """[(label, value)] for the keys of `d` that are not in `known`, in their order (empty ones left out)."""
    if not isinstance(d, dict):
        return []
    return [(label(k), text(v, lang)) for k, v in d.items()
            if str(k) not in known and not empty(v) and text(v, lang)]


def year(d) -> str:
    """The `year:` of a game or an option, as text ('' when there is none)."""
    v = d.get("year") if isinstance(d, dict) else None
    return "" if empty(v) else text(v)
