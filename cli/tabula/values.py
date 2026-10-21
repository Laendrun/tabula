"""Values: numbers and words defined once (in vault.yaml or a game's frontmatter) and written {=name} in the text.

    values:
      main: {2p: 7, 3p: 6, "*": 5}     # by player count (or option): becomes {2p: 7 | 3p: 6 | *: 5}
      target: 100                      # a plain value

{=main} is replaced, before the file is read, by the inline choice it stands for, so filtering, the site's
player picker, the book and `check` all treat it like a choice written by hand. A game's values win over the
vault's, and a translation's over the game's.
"""
from __future__ import annotations

import difflib
import re
from pathlib import Path

from .source import Issues
from .syntax import FENCE_RE, parse_cond

VALUE_RE = re.compile(r"(?<!\\)\{=\s*([^\s{}]*?)\s*\}")
NAME_RE = re.compile(r"^[A-Za-z0-9_][\w-]*$")
CODE_RE = re.compile(r"`[^`\n]*`")


def merged_values(vault_config: dict, *metas: dict) -> dict:
    """vault.yaml's values, then each frontmatter's (the last wins)."""
    out: dict = {}
    for src in (vault_config, *metas):
        v = (src or {}).get("values")
        if isinstance(v, dict):
            out.update({str(k): val for k, val in v.items()})
    return out


def value_problems(values) -> list[str]:
    """What is wrong in a `values:` mapping (as messages)."""
    if values is None:
        return []
    if not isinstance(values, dict):
        return ["'values' must be a mapping: name: value, or name: {2p: 7, \"*\": 5}"]
    out = []
    for name, v in values.items():
        if not NAME_RE.match(str(name)):
            out.append(f"value name '{name}': use letters, digits, - and _")
        if isinstance(v, dict):
            for k in v:
                if str(k).strip() != "*" and parse_cond(str(k)) is None:
                    out.append(f"value '{name}': '{k}' is not a condition (2p, 3-4p, 5+p, +variant, -variant, or \"*\")")
            if not v:
                out.append(f"value '{name}' is empty")
        elif isinstance(v, list):
            out.append(f"value '{name}' is a list; write {{2p: 7, \"*\": 5}} for values by player count")
        elif any(c in str(v) for c in "{}|"):
            out.append(f"value '{name}' can't contain {{ }} or |")
    return out


def value_text(v) -> str:
    """What {=name} becomes: the inline choice for a mapping, else the value as written."""
    if isinstance(v, dict):
        return "{" + " | ".join(f"{str(k).strip()}: {val}" for k, val in v.items()) + "}"
    if isinstance(v, bool):
        return "yes" if v else "no"
    return str(v)


def expand_values(lines: list[tuple[int, str]], values: dict, issues: Issues, path: Path,
                  strict: bool = True) -> list[tuple[int, str]]:
    """Replace each {=name} by its value, outside code. `strict`: an unknown name is an error."""
    out, fence = [], None
    for ln, t in lines:
        if fence:
            fence = None if t.strip().startswith(fence) else fence
            out.append((ln, t))
            continue
        if m := FENCE_RE.match(t):
            fence = m.group(1)
            out.append((ln, t))
            continue
        if "{=" not in t:
            out.append((ln, t))
            continue
        code = [c.span() for c in CODE_RE.finditer(t)]

        def repl(m):
            if any(a <= m.start() < b for a, b in code):
                return m.group(0)
            name = m.group(1)
            if name in values:
                return value_text(values[name])
            if not strict:
                return m.group(0)
            close = difflib.get_close_matches(name, list(values), n=1, cutoff=0.6)
            hint = f" (did you mean '{close[0]}'?)" if close else (" (define it under 'values:' in the frontmatter "
                                                                  "or in vault.yaml)")
            issues.error(path, ln, f"unknown value '{{={name}}}'{hint}")
            return m.group(0)
        out.append((ln, VALUE_RE.sub(repl, t)))
    return out
