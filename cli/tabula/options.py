"""Extension and variant details: what an option changes besides the rules.

    extensions:
      pandora:
        description: "Pandora's Box"
        players: 2-10          # the player counts the game gets with it (added to the base game's)
        duration: 10-50
        needs: [troublemaker]  # turned on with it
        excludes: [points]     # can't be used together

The short forms (`extensions: [pandora]`, `pandora: "description"`) still work.
"""
from __future__ import annotations

import difflib
import sys

from .syntax import Ctx, in_range, parse_range

OPTION_KEYS = ("description", "players", "duration", "needs", "excludes")


def names(v) -> list[str]:
    if v is None:
        return []
    if isinstance(v, (list, tuple)):
        return [str(x).lower() for x in v]
    return [s.strip().lower() for s in str(v).split(",") if s.strip()]


def option_info(game, name: str) -> dict:
    """The details of a variant or extension (case ignored): {} for the short forms."""
    for key in ("extensions", "variants"):
        v = game.meta.get(key)
        if isinstance(v, dict):
            for k, d in v.items():
                if str(k).lower() == name.lower():
                    return d if isinstance(d, dict) else {}
    return {}


def with_needs(game, chosen: set[str]) -> tuple[set[str], list[tuple[str, str]]]:
    """The chosen options plus the ones they need (and those need…); [(added, needed by)]."""
    enabled, added = set(chosen), []
    todo = list(chosen)
    while todo:
        o = todo.pop()
        for n in names(option_info(game, o).get("needs")):
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
        if n not in {k.lower() for k in game.options}:
            continue                       # check reports it
        print(f"tabula: +{by} needs +{n}: turned it on", file=sys.stderr)
    ctx.variants |= {n for n, _ in added if n in {k.lower() for k in game.options}}
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


def option_problems(game) -> list[str]:
    """What is wrong in the details of the variants and extensions (for check)."""
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
                if k not in OPTION_KEYS:
                    close = difflib.get_close_matches(str(k), OPTION_KEYS, n=1, cutoff=0.6)
                    out.append(f"'{name}': unknown detail '{k}'" + (f" (did you mean '{close[0]}'?)" if close else
                                                                  f" (use {', '.join(OPTION_KEYS)})"))
            for k in ("players", "duration"):
                if d.get(k) is not None and parse_range(d[k]) is None:
                    out.append(f"'{name}': invalid {k} '{d[k]}' (use N, N-M or N+)")
            for k in ("needs", "excludes"):
                for n in names(d.get(k)):
                    if n == str(name).lower():
                        out.append(f"'{name}' {k} itself")
                    elif n not in declared:
                        out.append(f"'{name}' {k} '{n}', which is not declared under variants or extensions")
            both = set(names(d.get("needs"))) & set(names(d.get("excludes")))
            if both:
                out.append(f"'{name}' both needs and excludes {', '.join(sorted(both))}")
    return out
