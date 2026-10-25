"""Extension and variant details: what an option changes besides the rules.

    extensions:
      pandora:
        description: "Pandora's Box"
        players: 2-10          # the player counts the game gets with it (added to the base game's)
        duration: 10-50
        year: 2019             # when it came out
        needs: [troublemaker]  # turned on with it; a name that isn't a variant or extension is another game
        excludes: [points]     # can't be used together

The short forms (`extensions: [pandora]`, `pandora: "description"`) still work. Other keys are your own:
they are kept and shown as they are (see fields.py).
"""
from __future__ import annotations

import difflib
import sys

from pathlib import Path

from .syntax import Ctx, in_range, parse_range
from .vault import game_named

OPTION_KEYS = ("description", "players", "duration", "year", "needs", "excludes")


def names(v) -> list[str]:
    return [n.lower() for n in raw_names(v)]


def raw_names(v) -> list[str]:
    """The names of a `needs`/`excludes` list as written: a list, or one string with commas."""
    if v is None:
        return []
    if isinstance(v, (list, tuple)):
        return [str(x).strip() for x in v if str(x).strip()]
    return [s.strip() for s in str(v).split(",") if s.strip()]


def needs_of(game, name: str) -> tuple[list[str], list[tuple[str, Path | None]]]:
    """What an option needs: (the variants and extensions it turns on, the other games it needs as
    [(name as written, the game's file when it is in the vault)]). `needs: [troublemaker, Bandido]`."""
    declared = {k.lower() for k in game.options}
    opts, games = [], []
    for n in raw_names(option_info(game, name).get("needs")):
        if n.lower() in declared:
            opts.append(n.lower())
        else:
            games.append((n, game_named(game.root, n) if game.root else None))
    return opts, games


def option_info(game, name: str) -> dict:
    """The details of a variant or extension (case ignored): {} for the short forms."""
    for key in ("extensions", "variants"):
        v = game.meta.get(key)
        if isinstance(v, dict):
            for k, d in v.items():
                if str(k).lower() == name.lower():
                    return d if isinstance(d, dict) else {}
    return {}


def needs_text(game, name: str) -> list[str]:
    """['troublemaker', 'Bandido']: what an option needs, the other games as written."""
    opts, games = needs_of(game, name)
    return opts + [g for g, _ in games]


def with_needs(game, chosen: set[str]) -> tuple[set[str], list[tuple[str, str]]]:
    """The chosen options plus the ones they need (and those need…); [(added, needed by)]."""
    enabled, added = set(chosen), []
    todo = list(chosen)
    while todo:
        o = todo.pop()
        for n in needs_of(game, o)[0]:
            if n not in enabled:
                enabled.add(n)
                added.append((n, o))
                todo.append(n)
    return enabled, added


def conflicts(game, enabled: set[str]) -> list[tuple[str, str]]:
    out = []
    for o in sorted(enabled):
        for x in names(option_info(game, o).get("excludes")):
            if x in enabled and (x, o) not in out:
                out.append((o, x))
    return out


def players_range(game, enabled: set[str] | None = None, everything: bool = False):
    """The player counts: the base game's, with those the enabled extensions add (every option's with --all)."""
    rng = list(parse_range(game.meta.get("players")) or [])
    opts = game.options if everything else {o: "" for o in (enabled or ())}
    for o in opts:
        extra = parse_range(option_info(game, o).get("players"))
        if extra:
            rng += extra
    return rng or None


def players_note(game) -> str:
    """'10 with +pandora': the player counts only some options give (for the facts and `list`)."""
    base = parse_range(game.meta.get("players")) or []
    parts = []
    for o in game.options:
        extra = parse_range(option_info(game, o).get("players"))
        if extra and any(not in_range(base, n) for lo, hi in extra for n in range(lo, int(min(hi, lo + 20)) + 1)):
            parts.append(f"{option_info(game, o).get('players')} +{o}")
    return ", ".join(parts)


def apply_options(game, ctx: Ctx, players: int | None) -> int | None:
    """For show/export/lookup/cards: turn on what the chosen options need, refuse options that exclude each
    other and player counts the game doesn't have (with these options). Returns an exit code, or None."""
    enabled, added = with_needs(game, ctx.variants)
    for n, by in added:
        print(f"tabula: +{by} needs +{n}: turned it on", file=sys.stderr)
    ctx.variants |= {n for n, _ in added}
    for o in sorted(ctx.variants):
        for g, _ in needs_of(game, o)[1]:
            print(f"tabula: +{o} needs the game {g}", file=sys.stderr)
    for a, b in conflicts(game, ctx.variants):
        print(f"tabula: +{a} and +{b} can't be used together", file=sys.stderr)
        return 2
    rng = players_range(game, ctx.variants, ctx.everything)
    if players is not None and rng and not in_range(rng, players):
        note = players_note(game)
        hint = f" (with extensions: {note})" if note and not ctx.everything else ""
        print(f"tabula: {game.title} is for {game.meta.get('players')} players, not {players}{hint}", file=sys.stderr)
        return 2
    return None


def option_problems(game) -> list[tuple[str, str]]:
    """What is wrong in the details of the variants and extensions (for check): [(level, message)]."""
    out = []
    declared = {k.lower() for k in game.options}
    for key in ("variants", "extensions"):
        v = game.meta.get(key)
        if not isinstance(v, dict):
            continue
        for name, d in v.items():
            if not isinstance(d, dict):
                continue
            for k in d:
                # your own details are fine, but one close to a known detail is probably a typo
                close = difflib.get_close_matches(str(k), OPTION_KEYS, n=1, cutoff=0.8)
                if k not in OPTION_KEYS and close:
                    out.append(("warning", f"'{name}': '{k}' looks like a typo of '{close[0]}' "
                                           "(other details are kept as they are)"))
            for k in ("players", "duration"):
                if d.get(k) is not None and parse_range(d[k]) is None:
                    out.append(("error", f"'{name}': invalid {k} '{d[k]}' (use N, N-M or N+)"))
            if d.get("year") is not None and not year_ok(d["year"]):
                out.append(("warning", f"'{name}': year should be a year, e.g. 2019 (got '{d['year']}')"))
            for k in ("needs", "excludes"):
                for raw in raw_names(d.get(k)):
                    n = raw.lower()
                    close = difflib.get_close_matches(n, sorted(declared), n=1, cutoff=0.8)
                    if n == str(name).lower():
                        out.append(("error", f"'{name}' {k} itself"))
                    elif n in declared:
                        continue
                    elif k == "excludes":
                        out.append(("error", f"'{name}' excludes '{n}', which is not declared under variants or "
                                             "extensions"))
                    elif close:            # needs: a name that isn't an option is another game, unless it's a typo
                        out.append(("error", f"'{name}' needs '{raw}', which is not declared under variants or "
                                             f"extensions: did you mean '{close[0]}'? (another game's name is fine)"))
            both = set(names(d.get("needs"))) & set(names(d.get("excludes")))
            if both:
                out.append(("error", f"'{name}' both needs and excludes {', '.join(sorted(both))}"))
    return out


def year_ok(v) -> bool:
    """2019, '2019' or '-500' (a year), not 'soon'."""
    return not isinstance(v, bool) and str(v).strip().lstrip("-").isdigit()
