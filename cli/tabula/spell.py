"""Spell checking for `tabula check --spell`: Hunspell dictionaries read by spylls (an optional dependency).

Dictionaries are not shipped with tabula (their licences differ). The first check in a language downloads
the free Hunspell dictionary for it (the `dictionary-<lang>` packages on npm, from LibreOffice and
others) into tabula's cache folder. Offline, put `<lang>.aff` and `<lang>.dic` there yourself.
"""
from __future__ import annotations

import difflib
import io
import json
import os
import re
import sys
import tarfile
import urllib.request
from pathlib import Path

from .syntax import BRACES_RE, FENCE_RE, parse_choice
from .source import raw_text
from .symbols import SYMBOL_RE

REGISTRY = "https://registry.npmjs.org/dictionary-{name}/latest"
WORD_RE = re.compile(r"(?<!\w)[^\W\d_]+(?:'[^\W\d_]+)*(?!\w)")    # whole words: not "er" of "1er"
INCLUDE_RE = re.compile(r"!\[\[[^\[\]\n]*\]\]")
REF_RE = re.compile(r"(?<!\\)\[\[([^\[\]|\n]+?)(?:\|([^\[\]\n]+?))?\]\]")
CODE_RE = re.compile(r"`[^`\n]*`")
URL_RE = re.compile(r"\b(?:https?://|www\.)\S+")
TAG_RE = re.compile(r"</?[A-Za-z][^<>\n]*>")
LINK_TARGET_RE = re.compile(r"\]\([^)\s]*\)")
FIELD_ANYWHERE_RE = re.compile(r"[^\W\d][\w -]*?::")
ALSO = {"en": "en-gb"}          # plain "en": British spellings are right too (the "en" dictionary is US)
FRONTMATTER_WORDS = ("title", "designer", "artist", "publisher", "series", "source", "location")


class SpellError(Exception):
    pass


def cache_dir() -> Path:
    """Where downloaded dictionaries are kept (TABULA_CACHE overrides it)."""
    if os.environ.get("TABULA_CACHE"):
        return Path(os.environ["TABULA_CACHE"]) / "dictionaries"
    if sys.platform == "win32":
        base = Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local")
    elif sys.platform == "darwin":
        base = Path.home() / "Library" / "Caches"
    else:
        base = Path(os.environ.get("XDG_CACHE_HOME") or Path.home() / ".cache")
    return base / "tabula" / "dictionaries"


def download(lang: str, folder: Path) -> Path:
    """Fetch the Hunspell dictionary for `lang` (fr, en, de, pt-br…) into `folder`; returns the base path."""
    names = [lang.lower()] + ([lang.split("-")[0].lower()] if "-" in lang else [])
    last = None
    for name in names:
        try:
            with urllib.request.urlopen(REGISTRY.format(name=name), timeout=20) as r:
                tarball = json.load(r)["dist"]["tarball"]
            with urllib.request.urlopen(tarball, timeout=60) as r:
                data = r.read()
        except Exception as e:            # no such dictionary, or offline
            last = e
            continue
        folder.mkdir(parents=True, exist_ok=True)
        with tarfile.open(fileobj=io.BytesIO(data)) as tar:
            for ext in ("aff", "dic"):
                member = tar.extractfile(f"package/index.{ext}")
                if member is None:
                    raise SpellError(f"the dictionary-{name} package has no index.{ext}")
                (folder / f"{lang}.{ext}").write_bytes(member.read())
        print(f"tabula: downloaded the '{lang}' spelling dictionary to {folder}", file=sys.stderr)
        return folder / lang
    raise SpellError(f"no '{lang}' spelling dictionary: download failed ({last}). Put {lang}.aff and "
                     f"{lang}.dic (Hunspell) in {folder}")


_loaded: dict = {}


def dictionary(lang: str):
    """The spylls Dictionary for a language, downloaded the first time."""
    if lang in _loaded:
        if isinstance(_loaded[lang], SpellError):
            raise _loaded[lang]
        return _loaded[lang]
    try:
        try:
            from spylls.hunspell import Dictionary
        except ImportError:
            raise SpellError("spell checking needs the spylls package: pipx inject tabula spylls "
                             "(or pip install 'tabula[spell]')") from None
        folder = cache_dir()
        base = folder / lang
        if not (base.with_suffix(".aff").exists() and base.with_suffix(".dic").exists()):
            base = download(lang, folder)
        _loaded[lang] = Dictionary.from_files(str(base))
    except SpellError as e:
        _loaded[lang] = e
        raise
    return _loaded[lang]


def word_list(path: Path) -> set[str]:
    if not path.is_file():
        return set()
    out = set()
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.split("#", 1)[0].strip()
        out |= {w.lower() for w in WORD_RE.findall(line.replace("’", "'"))}
    return out


def known_words(game, vault) -> set[str]:
    """Words that are right even if the dictionary doesn't know them: the game's own names, the vault's
    words.txt and the frontmatter's `words:`."""
    from .blocks import components_of
    names = [c["name"] for c in components_of(game.blocks)]

    def defs(blocks):
        for b in blocks:
            if b.kind == "def":
                names.append(b.term)
            defs(b.children)
    defs(game.blocks)
    meta = {**game.meta, **getattr(game, "tr_meta", {})}
    for key in FRONTMATTER_WORDS + ("words",):
        v = meta.get(key)
        names += [str(x) for x in v] if isinstance(v, list) else [str(v)] if v else []
    names += list(game.options)
    out = set()
    for n in names:
        out |= {w.lower() for w in WORD_RE.findall(n.replace("’", "'"))}
    out |= word_list(vault.root / "words.txt")
    out |= word_list(vault.root / f"words.{game.language}.txt")
    return out


def prose(line: str) -> str:
    """The words of a source line that are text, with names, conditions, code and links blanked out."""
    def blank(m):
        return " " * len(m.group(0))
    t = line.replace("’", "'")
    for rx in (CODE_RE, URL_RE, TAG_RE, INCLUDE_RE, LINK_TARGET_RE, SYMBOL_RE):
        t = rx.sub(blank, t)
    t = REF_RE.sub(lambda m: " " * (m.start(2) - m.start()) + m.group(2) + "  " if m.group(2) else blank(m), t)

    def braces(m):
        body = m.group(1)
        branches = parse_choice(body) if ":" in body else None
        if not branches:
            return blank(m)
        return " " + " | ".join(text for _, text in branches) + " "
    t = BRACES_RE.sub(braces, t)
    t = re.sub(r"\\[\[\]{}!\\*#]", "  ", t)
    t = FIELD_ANYWHERE_RE.sub(blank, t) if "::" in t else t
    return t.replace("_", " ")                                # _italics_


def check_spelling(game, vault, lang: str | None = None) -> list[tuple[int, str]]:
    """(line, message) for each unknown word, once per line. Raises SpellError without a dictionary."""
    lang = lang or game.language
    d = dictionary(lang)
    known = known_words(game, vault)
    path = game.body_path or game.path
    text = raw_text(path).lstrip("\ufeff").replace("\r\n", "\n")
    text = re.sub(r"<!--.*?-->", lambda m: "\n" * m.group(0).count("\n"), text, flags=re.S)
    lines = text.split("\n")
    start = 0
    if lines and lines[0].strip() == "---":                    # skip the frontmatter
        for i in range(1, len(lines)):
            if lines[i].strip() in ("---", "..."):
                start = i + 1
                break
    cache: dict[str, bool] = {}
    other = []                     # the second dictionary (en-gb for en), loaded on the first miss

    def lookup(word: str) -> bool:
        if d.lookup(word):
            return True
        if lang.lower() not in ALSO:
            return False
        if not other:
            try:
                other.append(dictionary(ALSO[lang.lower()]))
            except SpellError:
                other.append(None)
        return bool(other[0] and other[0].lookup(word))

    def ok(w: str) -> bool:
        if w not in cache:
            low = w.lower()
            parts = [w] + ([w.split("'")[-1]] if "'" in w else [])
            parts += [p.replace("oe", "œ").replace("Oe", "Œ") for p in parts if "oe" in p.lower()]   # oeil
            cache[w] = (low in known or w.isupper() or len(w) < 2
                        or any(p.lower() in known or lookup(p) for p in parts))
        return cache[w]

    out, in_code = [], False
    for i in range(start, len(lines)):
        if FENCE_RE.match(lines[i]):
            in_code = not in_code
            continue
        if in_code:
            continue
        seen = set()
        for w in WORD_RE.findall(prose(lines[i])):
            if w in seen or ok(w):
                continue
            seen.add(w)
            close = difflib.get_close_matches(w.lower(), known, n=1, cutoff=0.8)
            hint = f" (did you mean '{close[0]}'?)" if close else ""
            out.append((i + 1, f"unknown word '{w}'{hint}"))
    return out
