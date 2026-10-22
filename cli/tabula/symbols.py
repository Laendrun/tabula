"""Symbols: the icons of a game (gold, keys, stars, card suits…) written :name: in the text.

    symbols:                         # in vault.yaml (every game) or a game's frontmatter
      star: ⭐                        # text: an emoji or a word, shown as it is everywhere
      gold: media/gold.png           # an image (relative to vault.yaml's folder, or to the game's folder)
      key: {image: media/key.png, text: "🔑"}     # an image, and what the terminal shows instead

:name: is replaced when the file is read. A text symbol becomes its text. An image symbol becomes a small
inline image, ![sym:TEXT](path), that the site, the book and the HTML export draw at the size of the text
and the terminal writes as TEXT. Only defined names are replaced: other :words: stay as they are.
"""
from __future__ import annotations

import os
import re
from pathlib import Path

from .source import file_problem
from .syntax import FENCE_RE

SYMBOL_RE = re.compile(r"(?<![^\W\d])(?<![_:\\/]):([A-Za-z0-9][\w+-]*):(?![\w:/])")   # "3:gold:" too
CODE_RE = re.compile(r"`[^`\n]*`")
IMAGE_EXTS = (".png", ".jpg", ".jpeg", ".gif", ".svg", ".webp")
SYM_ALT = "sym:"


def symbol_parts(v) -> tuple[str | None, str | None]:
    """(image path, text) of a symbol definition."""
    if isinstance(v, dict):
        img, text = v.get("image"), v.get("text")
        return (str(img) if img else None), (str(text) if text is not None else None)
    s = str(v)
    if s.lower().endswith(IMAGE_EXTS) and not s.startswith("http"):
        return s, None
    return None, s


def merged_symbols(vault_root: Path, base_dir: Path, vault_config: dict, *metas: dict) -> dict:
    """name -> (image path relative to the game's folder or None, text): the vault's, then the game's."""
    out: dict = {}
    for src, folder in ((vault_config, vault_root), *((m, base_dir) for m in metas)):
        syms = (src or {}).get("symbols")
        if not isinstance(syms, dict):
            continue
        for name, v in syms.items():
            img, text = symbol_parts(v)
            if img:
                img = Path(os.path.relpath(folder / img, base_dir)).as_posix()
            out[str(name)] = (img, text)
    return out


def symbol_problems(symbols, folder: Path, root: Path | None = None) -> list[str]:
    if symbols is None:
        return []
    if not isinstance(symbols, dict):
        return ["'symbols' must be a mapping: name: ⭐, name: media/x.png, or name: {image: …, text: …}"]
    out = []
    for name, v in symbols.items():
        if not re.fullmatch(r"[A-Za-z0-9][\w+-]*", str(name)):
            out.append(f"symbol name '{name}': use letters, digits, -, + and _")
        if isinstance(v, dict) and not set(v) <= {"image", "text"}:
            out.append(f"symbol '{name}': only 'image' and 'text' can be given")
        if isinstance(v, (list, type(None))):
            out.append(f"symbol '{name}' has no value")
            continue
        img, _ = symbol_parts(v)
        if img and re.search(r"\s", img):
            out.append(f"symbol '{name}': the image path can't contain spaces ({img})")
        elif img and (why := file_problem(folder, img, root or folder)):
            out.append(f"symbol '{name}': image {why}: {img}")
    return out


def symbol_text(name: str, sym) -> str:
    img, text = sym
    if img:
        return f"![{SYM_ALT}{text or name}]({img})"
    return text or name


def expand_symbols(lines: list[tuple[int, str]], symbols: dict) -> list[tuple[int, str]]:
    """Replace each defined :name: outside code."""
    if not symbols:
        return lines
    out, fence = [], None
    for ln, t in lines:
        if fence:
            fence = None if t.strip().startswith(fence) else fence
        elif m := FENCE_RE.match(t):
            fence = m.group(1)
        elif ":" in t:
            code = [c.span() for c in CODE_RE.finditer(t)]
            t = SYMBOL_RE.sub(lambda m: m.group(0) if m.group(1) not in symbols
                              or any(a <= m.start() < b for a, b in code)
                              else symbol_text(m.group(1), symbols[m.group(1)]), t)
        out.append((ln, t))
    return out
