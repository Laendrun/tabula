"""Shared fragments: `![[deck-52]]` inserts vault/_shared/deck-52.game into a game, `![[deck-52#Glossaire]]`
one of its sections. Expanded on the raw lines, before a game is parsed."""
from __future__ import annotations

import re
from pathlib import Path

from .blocks import QUIET_END
from .source import Issue, Issues, read_source
from .syntax import FENCE_RE, HEADING_RE, fold

SHARED_DIR = "_shared"
INCLUDE_RE = re.compile(r"^(\s*)!\[\[([^\[\]#|\n]+?)(?:#([^\[\]|\n]+))?\]\]\s*$")
END_RE = re.compile(r"^-{3,}\s*$")
MAX_DEPTH = 8


def fragment_path(root: Path, name: str, lang: str | None) -> Path | None:
    """_shared/<name>.<lang>.game when it exists, else _shared/<name>.game."""
    base = root / SHARED_DIR
    if not re.fullmatch(r"[^/\\:]+", name) or name.strip(".") == "" or name.startswith("."):
        return None                     # a name, not a path: ![[../x]] or ![[/etc/x]] never leave _shared/
    for cand in ([base / f"{name}.{lang}.game"] if lang else []) + [base / f"{name}.game"]:
        if cand.is_file() and cand.resolve().is_relative_to(base.resolve()):
            return cand
    return None


def fragment_files(root: Path) -> list[Path]:
    base = root / SHARED_DIR
    return sorted(base.glob("*.game")) if base.is_dir() else []


def heading_title(text: str) -> tuple[str, list[str]]:
    """A heading's plain title and its roles: '## ! Cartes [[x]] {+e #cards}' -> ('Cartes x', ['cards'])."""
    roles = []
    if m := re.search(r"\s*\{([^{}]*)\}\s*$", text):
        roles = [r[1:] for r in m.group(1).split() if r.startswith("#")]
        text = text[: m.start()]
    text = re.sub(r"\[\[#?([^\]|]+)(?:\|([^\]]*))?\]\]", lambda r: r.group(2) or r.group(1), text)
    return text.lstrip("!").strip(), roles


def sections_of(texts: list[str]) -> list[str]:
    out, code = [], False
    for t in texts:
        if FENCE_RE.match(t):
            code = not code
        elif not code and (m := HEADING_RE.match(t)):
            title, roles = heading_title(m.group(2))
            out.append(title + "".join(f" #{r}" for r in roles))
    return out


def select_section(texts: list[str], want: str) -> tuple[list[str], int] | None:
    """The content of the section titled (or with the role) `want`, without its heading, and its level."""
    want_key, want_role = fold(want), want.strip().lower()
    code = False
    start = level = None
    for i, t in enumerate(texts):
        if FENCE_RE.match(t):
            code = not code
        if code or not (m := HEADING_RE.match(t)):
            continue
        title, roles = heading_title(m.group(2))
        if fold(title) == want_key or want_role in roles:
            start, level = i, len(m.group(1))
            break
    if start is None:
        return None
    body, deeper, code = [], [], False
    for t in texts[start + 1:]:
        if FENCE_RE.match(t):
            code = not code
        elif not code:
            if m := HEADING_RE.match(t):
                n = len(m.group(1))
                if n <= level:
                    break
                while deeper and deeper[-1] >= n:
                    deeper.pop()
                deeper.append(n)
            elif END_RE.match(t):
                if not deeper:
                    break                # "---" closing the selected section itself
                deeper.pop()
        body.append(t)
    while body and not body[-1].strip():
        body.pop()
    return body, level


def shift_headings(texts: list[str], base: int, under: int) -> list[str]:
    """Headings of level base+k become level under+k (at most 6): fragment sections nest where they land."""
    out, code = [], False
    for t in texts:
        if FENCE_RE.match(t):
            code = not code
        elif not code and (m := HEADING_RE.match(t)):
            n = min(6, max(1, under + len(m.group(1)) - base))
            t = "#" * n + t[len(m.group(1)):]
        out.append(t)
    return out


def expand_includes(lines: list[tuple[int, str]], root: Path, lang: str | None, issues: Issues, path: Path,
                    _stack: tuple = (), _at: tuple | None = None) -> list[tuple[int, str]]:
    """Replace every `![[name]]` / `![[name#Section]]` line by the fragment's lines.

    Included lines keep the include's line number (so problems point at the `![[…]]` line) and its
    indentation; the fragment's headings are nested under the section the include is in."""
    out: list[tuple[int, str]] = []
    level, code = 0, False

    def report(ln: int, msg: str):
        p, l = _at or (path, ln)
        issues.append(Issue("error", Path(p), l, msg))

    for ln, t in lines:
        if FENCE_RE.match(t):
            code = not code
        if code:
            out.append((ln, t))
            continue
        if m := HEADING_RE.match(t):
            level = len(m.group(1))
        m = INCLUDE_RE.match(t)
        if not m:
            out.append((ln, t))
            continue
        indent, name, section = m.group(1), m.group(2).strip(), m.group(3)
        fp = fragment_path(root, name, lang)
        if fp is None:
            report(ln, f"no shared fragment '{name}': looked for {SHARED_DIR}/{name}.game in the vault")
            continue
        if fp.resolve() in _stack:
            report(ln, f"'{name}' includes itself (through {' → '.join(p.stem for p in _stack)})")
            continue
        if len(_stack) >= MAX_DEPTH:
            report(ln, f"fragments nested more than {MAX_DEPTH} deep at '{name}'")
            continue
        sub = Issues()
        _, flines = read_source(fp, sub)
        for i in sub:
            report(ln, f"in {SHARED_DIR}/{fp.name}: {i.msg}")
        flines = expand_includes(flines, root, lang, issues, path, _stack + (fp.resolve(),), _at or (path, ln))
        texts = [x for _, x in flines]
        base = 0
        if section:
            picked = select_section(texts, section)
            if picked is None:
                avail = sections_of(texts)
                report(ln, f"no section '{section}' in {SHARED_DIR}/{fp.name}; "
                           f"sections: {', '.join(avail) or '(none)'}")
                continue
            texts, base = picked
        while texts and not texts[0].strip():
            texts = texts[1:]
        shifted = shift_headings(texts, base, level)
        for x in shifted:
            out.append((ln, indent + x if x.strip() else x))
        # close the sections the fragment opened, so the game's next lines are back where the include was
        out += [(ln, "")] + [(ln, QUIET_END)] * open_sections(shifted, level)
    return out


def open_sections(texts: list[str], level: int) -> int:
    """How many headings deeper than `level` are still open at the end of `texts`."""
    stack, code = [], False
    for t in texts:
        if FENCE_RE.match(t):
            code = not code
        elif not code and (m := HEADING_RE.match(t)):
            n = len(m.group(1))
            while stack and stack[-1] >= n:
                stack.pop()
            if n > level:
                stack.append(n)
        elif not code and (END_RE.match(t) or t == QUIET_END) and stack:
            stack.pop()
    return len(stack)
