"""The vault: finding games and their translations, loading them."""
from __future__ import annotations

import sys
import os
from dataclasses import dataclass, field
from pathlib import Path

try:
    import yaml
except ImportError:  # pragma: no cover
    sys.exit("tabula needs PyYAML:  pip install pyyaml")

from .syntax import LANG_RE, split_lang
from .fragments import SHARED_DIR, expand_includes
from .values import expand_values, merged_values, value_problems
from .symbols import expand_symbols, merged_symbols, symbol_problems
from .source import Issues, local_file, read_source
from .blocks import Block, parse_blocks

IMAGE_EXTS = (".jpg", ".jpeg", ".png", ".webp", ".gif", ".avif", ".svg")


@dataclass
class Game:
    slug: str
    path: Path
    folder: Path | None
    meta: dict
    blocks: list[Block]
    lines: list[tuple[int, str]]
    issues: Issues
    language: str
    default_language: str
    languages: list[str]
    fallback: bool = False
    body_path: Path | None = None
    tr_meta: dict = field(default_factory=dict)
    root: Path | None = None          # the vault: files a game names must be inside it

    @property
    def title(self) -> str:
        return str(self.meta.get("title") or self.slug)

    @property
    def base_dir(self) -> Path:
        return self.folder or self.path.parent

    @property
    def cover(self) -> Path | None:
        """The box image: `cover:` in the frontmatter when it's set, else media/cover.* or media/<slug>_cover.*
        found next to the game (for a standalone game, only <slug>_cover.*, since media/ is shared).
        `cover: false` means no cover. The path may not exist when `cover:` names a missing file."""
        v = self.meta.get("cover")
        if v is False:
            return None
        if v not in (None, ""):
            p = local_file(self.base_dir, str(v), self.root)
            return p if p is not None else None          # outside the vault: never used (check says so)
        media = self.base_dir / "media"
        if not media.is_dir():
            return None
        names = [f"{self.slug}_cover", f"{self.slug}-cover"] + (["cover"] if self.folder else [])
        images = sorted(f for f in media.iterdir() if f.is_file() and f.suffix.lower() in IMAGE_EXTS)
        for name in names:
            for f in images:
                if f.stem.lower() == name.lower():
                    return f
        return None

    def _options(self, key: str) -> dict[str, str]:
        v = self.meta.get(key)
        if isinstance(v, dict):         # name: "description", or name: {description: …, players: …}
            return {str(k): "" if d is None else str(d.get("description") or "") if isinstance(d, dict) else str(d)
                    for k, d in v.items()}
        if isinstance(v, list):
            return {str(k): "" for k in v}
        return {}

    @property
    def variants(self) -> dict[str, str]:
        return self._options("variants")

    @property
    def extensions(self) -> dict[str, str]:
        return self._options("extensions")

    @property
    def options(self) -> dict[str, str]:
        """Everything a {+name} condition can refer to: variants and extensions."""
        return {**self.variants, **self.extensions}


class Vault:
    def __init__(self, root: Path):
        self.root = root.resolve()
        self.config: dict = {}
        self.issues = Issues()
        cfg = self.root / "vault.yaml"
        if cfg.exists():
            try:
                self.config = yaml.safe_load(cfg.read_text(encoding="utf-8")) or {}
            except yaml.YAMLError as e:
                self.issues.error(cfg, 1, f"invalid YAML: {e}")
            if not isinstance(self.config, dict):          # a list or a word: nothing tabula can use
                self.issues.error(cfg, 1, "vault.yaml must be settings written as 'key: value' (name:, language:…)")
                self.config = {}
            for msg in value_problems(self.config.get("values")) + symbol_problems(self.config.get("symbols"), self.root):
                self.issues.error(cfg, 1, msg)
        self.language = str(self.config.get("language") or "en")
        if not LANG_RE.match(self.language):          # it names pages and files: a code, nothing else
            self.issues.error(cfg, 1, f"language '{self.language}' is not a language code (fr, en, de, pt-BR…)")
            self.language = "en"

    def discover(self) -> list[Path]:
        found = []
        for g in sorted(self.root.glob("*.game")):
            slug, lang = split_lang(g.stem)
            if lang is None:
                found.append(g)
            elif not (self.root / f"{slug}.game").exists():
                self.issues.error(g, 0, f"translation without the default-language file '{slug}.game'")
        for d in sorted(p for p in self.root.iterdir() if p.is_dir() and not p.name.startswith((".", "_"))):
            games = sorted(d.glob("*.game"))
            if not games:
                continue
            expected = d / f"{d.name}.game"
            for g in games:
                if split_lang(g.stem)[0] != d.name:
                    self.issues.error(g, 0, f"file should be named '{d.name}.game' (or '{d.name}.<lang>.game')")
            if expected in games:
                found.append(expected)
            else:
                self.issues.error(d, 0, f"missing default-language file '{expected.name}'")
        seen: dict[str, Path] = {}
        unique = []
        for g in found:                     # x.game and x/x.game: two games with one name
            if g.stem in seen:
                if not any(i.msg.startswith(f"two games named '{g.stem}'") for i in self.issues):
                    self.issues.error(g, 0, f"two games named '{g.stem}': {seen[g.stem].relative_to(self.root)} and "
                                            f"{g.relative_to(self.root)}; rename or remove one (this one is ignored)")
                continue
            seen[g.stem] = g
            unique.append(g)
        return unique

    def find(self, ref: str) -> Path:
        p = Path(ref)
        if p.is_file() and p.suffix == ".game":
            slug, lang = split_lang(p.stem)
            return (p.parent / f"{slug}.game").resolve() if lang else p.resolve()
        if p.is_dir() and (p / f"{p.name}.game").exists():
            return (p / f"{p.name}.game").resolve()
        for cand in (self.root / ref / f"{ref}.game", self.root / f"{ref}.game"):
            if cand.exists():
                return cand
        games = self.discover()
        hits = [g for g in games if ref.lower() in g.stem.lower()]
        if len(hits) == 1:
            return hits[0]
        raise SystemExit(f"tabula: game '{ref}' not found in {self.root}\n"
                         f"  available: {', '.join(g.stem for g in games) or '(none)'}")

    def load(self, path: Path, lang: str | None = None) -> Game:
        issues = Issues()
        slug = path.stem
        folder = None if path.parent.resolve() == self.root else path.parent
        meta, lines = read_source(path, issues)
        default_lang = str(meta.get("language") or self.language)
        if not LANG_RE.match(default_lang):
            issues.error(path, 1, f"language '{default_lang}' is not a language code (fr, en, de, pt-BR…)")
            default_lang = self.language
        if path.parent.name != SHARED_DIR:            # a fragment's includes are expanded where it's used
            lines = expand_includes(lines, self.root, default_lang, issues, path)
        langs = {default_lang}
        for f in path.parent.glob(f"{slug}.*.game"):
            s, l = split_lang(f.stem)
            if s == slug and l:
                langs.add(l)
        languages = sorted(langs)
        body_path, tr_meta, fallback = path, {}, False
        if lang and lang != default_lang:
            tr = path.parent / f"{slug}.{lang}.game"
            if tr.exists():
                tr_meta, lines = read_source(tr, issues)
                lines = expand_includes(lines, self.root, lang, issues, tr)
                merged = {**meta, **tr_meta}
                for key in ("variants", "extensions", "values", "symbols"):
                    if isinstance(meta.get(key), dict) and isinstance(tr_meta.get(key), dict):
                        merged[key] = {**meta[key], **tr_meta[key]}
                        for k, d in meta[key].items():   # a translated description keeps the details
                            if isinstance(d, dict) and k in tr_meta[key] and not isinstance(tr_meta[key][k], dict):
                                merged[key][k] = {**d, "description": tr_meta[key][k]}
                meta, body_path = merged, tr
            else:
                fallback = True
        language = lang if (lang and not fallback) else default_lang
        lines = expand_values(lines, merged_values(self.config, meta), issues, body_path,
                              strict=path.parent.name != SHARED_DIR)    # a fragment: the game's values
        lines = expand_symbols(lines, merged_symbols(self.root, folder or path.parent, self.config, meta))
        return Game(slug, path, folder, meta, parse_blocks(lines), lines, issues, language,
                    default_lang, languages, fallback, body_path, tr_meta, root=self.root)


def open_vault(arg: str | None, ref: str | None = None) -> Vault:
    if arg:
        return Vault(Path(arg))
    if os.environ.get("TABULA_VAULT"):
        return Vault(Path(os.environ["TABULA_VAULT"]))
    if ref and Path(ref).exists():
        p = Path(ref).resolve()
        for anc in [p] + list(p.parents):
            if (anc / "vault.yaml").exists():
                return Vault(anc)
        d = p if p.is_dir() else p.parent
        if d.name == SHARED_DIR:                     # a shared fragment: the vault is the folder above
            return Vault(d.parent)
        return Vault(d.parent if (d / f"{d.name}.game").exists() else d)
    return Vault(Path.cwd())
