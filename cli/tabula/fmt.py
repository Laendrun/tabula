"""`tabula fmt`: tidy .game files without changing what they say.

The changes: line endings, trailing spaces, one blank line around headings and `---` section ends, no runs of
blank lines, aligned table columns, and one newline at the end. The frontmatter, code blocks and comments are
left as they are. Each result is parsed again and compared with the original: a file that would read
differently is not changed (and reported), so formatting can never change a game.
"""
from __future__ import annotations

import dataclasses
import sys
import unicodedata
from pathlib import Path

from .blocks import parse_blocks, table_cells
from .source import Issues, UNSAVED, read_source
from .syntax import END_RE, FENCE_RE, HEADING_RE
from .vault import open_vault
from .sheet import sheets_of


def width(s: str) -> int:
    """Columns a string takes in a monospaced font (wide characters count twice, accents nothing)."""
    return sum(0 if unicodedata.combining(c) else 2 if unicodedata.east_asian_width(c) in "WF" else 1 for c in s)


def is_separator(cells: list[str]) -> bool:
    return any(cells) and all(not c or set(c.strip(":")) == {"-"} for c in cells)


def format_table(rows: list[str]) -> list[str]:
    indent = rows[0][: len(rows[0]) - len(rows[0].lstrip())]
    table = [table_cells(r) for r in rows]
    spaced = any(is_separator(c) and r.strip().startswith("| ") for r, c in zip(rows, table))   # | --- | style
    n = max(len(r) for r in table)
    widths = [3 if spaced else 1] * n      # a separator needs 3 dashes: | --- | has none to spare
    for r in table:
        if is_separator(r):
            continue
        for j, c in enumerate(r):
            widths[j] = max(widths[j], width(c))
    out = []
    for r in table:
        if is_separator(r):            # |-----|:----:|, as wide as the column and its spaces
            cells = []
            for j, c in enumerate(r):
                left, right = c.startswith(":"), c.endswith(":") and len(c) > 1
                n = widths[j] + (0 if spaced else 2) - left - right
                cells.append((":" if left else "") + "-" * n + (":" if right else ""))
            out.append(indent + ("| " + " | ".join(cells) + " |" if spaced else "|" + "|".join(cells) + "|"))
        else:
            out.append(indent + "| " + " | ".join(c + " " * (widths[j] - width(c)) for j, c in enumerate(r)) + " |")
    return out


def format_text(text: str) -> str:
    """The tidied text (no safety check: see `format_game`). Windows line endings stay Windows line endings."""
    crlf = text.count("\r\n") > text.count("\n") / 2
    lines = text.lstrip("﻿").replace("\r\n", "\n").replace("\r", "\n").split("\n")
    out: list[str] = []
    i = 0
    if lines and lines[0].strip() == "---":                       # frontmatter: kept as written
        end = next((k for k in range(1, len(lines)) if lines[k].strip() in ("---", "...")), None)
        if end is not None:
            out = [l.rstrip() for l in lines[: end + 1]]
            i = end + 1
            while i < len(lines) and not lines[i].strip():
                i += 1
            if i < len(lines):
                out.append("")

    def blank():
        if out and out[-1] != "":
            out.append("")

    fence, comment = None, False
    while i < len(lines):
        t = lines[i]
        if fence:                                                   # code: as written
            out.append(t)
            if t.strip().startswith(fence):
                fence = None
            i += 1
            continue
        if comment:
            out.append(t.rstrip())
            comment = "-->" not in t
            i += 1
            continue
        if m := FENCE_RE.match(t):
            fence = m.group(1)
            out.append(t.rstrip())
            i += 1
            continue
        t = t.rstrip()
        if "<!--" in t and "-->" not in t[t.index("<!--"):]:
            comment = True
            out.append(t)
            i += 1
            continue
        if not t:
            blank()
            i += 1
            continue
        if t.lstrip().startswith("|"):
            rows = []
            while i < len(lines) and lines[i].lstrip().startswith("|"):
                rows.append(lines[i].rstrip())
                i += 1
            out += format_table(rows)
            continue
        if HEADING_RE.match(t) or END_RE.match(t):
            blank()
            out.append(t)
            out.append("")
            i += 1
            continue
        out.append(t)
        i += 1
    while out and out[-1] == "":
        out.pop()
    eol = "\r\n" if crlf else "\n"
    return eol.join(out) + eol


def _shape(blocks) -> list:
    """The parsed blocks without line numbers, to compare two versions of a file."""
    def clean(x):
        if isinstance(x, dict):
            return {k: clean(v) for k, v in x.items() if k not in ("line", "src", "field_lines", "reopens")}
        if isinstance(x, (list, tuple)):
            if len(x) == 2 and isinstance(x[0], int) and isinstance(x[1], list):     # a table row (line, cells)
                cells = x[1]
                if is_separator(cells):        # |---|---| and | --- | --- | are the same separator
                    cells = [(":" if c.startswith(":") else "") + "-" + (":" if c.endswith(":") else "") for c in cells]
                return clean(cells)
            if len(x) == 3 and isinstance(x[2], int) and isinstance(x[0], str):      # a definition item
                return clean(list(x[:2]))
            return [clean(v) for v in x]
        return x
    return [clean(dataclasses.asdict(b)) for b in blocks]


def parsed(path: Path, text: str):
    UNSAVED[path.resolve()] = text
    try:
        meta, lines = read_source(path, Issues())
    finally:
        UNSAVED.pop(path.resolve(), None)
    return meta, _shape(parse_blocks(lines))


def format_game(path: Path, text: str) -> tuple[str, bool]:
    """(formatted text, safe): `safe` is False when the result would read differently (then it's not used)."""
    new = format_text(text)
    if new == text:
        return text, True
    return new, parsed(path, new) == parsed(path, text)


def cmd_fmt(args) -> int:
    if args.stdin:
        if len(args.games) != 1 or not Path(args.games[0]).is_file():
            raise SystemExit("tabula: --stdin needs exactly one .game file (the file being edited)")
        path = Path(args.games[0])
        text = sys.stdin.buffer.read().decode("utf-8", errors="replace")
        new, safe = format_game(path, text)
        # as bytes: on Windows, text mode would turn each \r\n into \r\r\n (a blank line after every line)
        sys.stdout.flush()
        out = getattr(sys.stdout, "buffer", None)
        if out is not None:
            out.write((new if safe else text).encode("utf-8"))
            out.flush()
        else:                                      # tests capture stdout as text
            sys.stdout.write(new if safe else text)
        if not safe:
            print(f"tabula: not formatted: the result would read differently ({path.name})", file=sys.stderr)
        return 0 if safe else 1
    vault = open_vault(args.vault, args.games[0] if args.games else None)
    if args.games:
        paths = []
        for g in args.games:
            p = vault.find(g)
            paths += [p] + sorted(f for f in p.parent.glob(f"{p.stem}.*.game"))   # its translations too
            paths += sheets_of(p, vault.root)                                     # and its score sheets
    else:
        from .fragments import fragment_files
        paths = [p for p in vault.root.rglob("*.game")] + fragment_files(vault.root) + list(vault.root.rglob("*.sheet"))
    changed = unsafe = 0
    for p in sorted(set(paths)):
        text = p.read_bytes().decode("utf-8", errors="replace")        # as written: keeps \r\n
        new, safe = format_game(p, text)
        rel = p.relative_to(vault.root) if p.is_relative_to(vault.root) else p
        if not safe:
            unsafe += 1
            print(f"not formatted (the result would read differently, please report it): {rel}")
        elif new != text:
            changed += 1
            if args.check:
                print(f"would format: {rel}")
            else:
                p.write_text(new, encoding="utf-8", newline="\n")
                print(f"formatted: {rel}")
    verb = "would be formatted" if args.check else "formatted"
    print(f"{len(set(paths))} file(s), {changed} {verb}" + (f", {unsafe} left as they are" if unsafe else ""))
    return 1 if unsafe or (args.check and changed) else 0
