"""`tabula new`: start a game file, either blank (`tabula new SLUG`, works offline) or with its frontmatter
filled from BoardGameGeek (`tabula new bgg ID [SLUG]`)."""
from __future__ import annotations

import os
import re
import sys
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path

import yaml

from ._version import __version__
from .vault import Vault, open_vault

BGG = "https://boardgamegeek.com/xmlapi2"
USER_AGENT = f"tabula/{__version__} (+https://github.com/Laendrun/tabula)"

SECTIONS = {   # the usual sections of a rulebook, with their roles, per language
    "fr": [("Matériel", "components"), ("But du jeu", "goal"), ("Mise en place", "setup"),
           ("Déroulement", "play"), ("Fin de partie", "end"), ("Glossaire", "glossary")],
    "en": [("Components", "components"), ("Goal", "goal"), ("Setup", "setup"),
           ("Play", "play"), ("End of the game", "end"), ("Glossary", "glossary")],
    "de": [("Spielmaterial", "components"), ("Spielziel", "goal"), ("Spielaufbau", "setup"),
           ("Spielablauf", "play"), ("Spielende", "end"), ("Glossar", "glossary")],
}
TODO = {"fr": "à écrire", "en": "to write", "de": "zu schreiben"}


class BggError(Exception):
    pass


def slugify(title: str) -> str:
    """'Les Aventuriers du Rail : Europe' -> 'les-aventuriers-du-rail-europe' (accents dropped, words kept)."""
    s = "".join(c for c in unicodedata.normalize("NFKD", title) if not unicodedata.combining(c)).lower()
    return re.sub(r"[^a-z0-9]+", "-", s).strip("-") or "game"


def fetch(url: str, token: str | None = None) -> bytes:
    """GET a URL (the BGG API, or a cover image). Replaced in tests."""
    headers = {"User-Agent": USER_AGENT}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=20) as r:
            return r.read()
    except urllib.error.HTTPError as e:
        if e.code in (401, 403):
            raise BggError("BoardGameGeek refused the request: the token is missing, wrong or expired "
                           "(set BGG_TOKEN, see 'tabula new --help')") from e
        if e.code == 429:
            raise BggError("BoardGameGeek says too many requests; wait a minute and try again") from e
        raise BggError(f"BoardGameGeek answered HTTP {e.code} for {url}") from e
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        reason = getattr(e, "reason", e)
        raise BggError(f"can't reach BoardGameGeek ({reason}); without internet, use 'tabula new SLUG'") from e


def value(item, tag: str) -> str:
    el = item.find(tag)
    return (el.get("value") or "").strip() if el is not None else ""


def span(lo: str, hi: str) -> str | int | None:
    """'3','4' -> '3-4'; '4','4' -> 4; '0','0' -> None."""
    a, b = int(lo or 0), int(hi or 0)
    if not a and not b:
        return None
    if not a or not b or a == b:
        return a or b
    return f"{min(a, b)}-{max(a, b)}"


def bgg_game(game_id: str, token: str | None) -> dict:
    """Frontmatter and a few extras for one BGG game: {meta, image, names}."""
    root = ET.fromstring(fetch(f"{BGG}/thing?id={urllib.parse.quote(game_id)}&type=boardgame,boardgameexpansion",
                               token))
    item = root.find("item")
    if item is None:
        raise BggError(f"no game with id {game_id} on BoardGameGeek")
    names = [n.get("value", "") for n in item.findall("name")]
    primary = next((n.get("value") for n in item.findall("name") if n.get("type") == "primary"), names[0] if names else "")

    def links(kind):
        return [l.get("value", "") for l in item.findall("link") if l.get("type") == kind
                and l.get("value") not in ("(Uncredited)", "(Unknown)", "(Self-Published)", "(Public Domain)")]

    categories = links("boardgamecategory")
    meta: dict = {"title": primary}
    if (players := span(value(item, "minplayers"), value(item, "maxplayers"))) is not None:
        meta["players"] = players
    duration = span(value(item, "minplaytime"), value(item, "maxplaytime")) or span(value(item, "playingtime"), "0")
    if duration:
        meta["duration"] = duration
    if (age := value(item, "minage")) and age != "0":
        meta["age"] = int(age)
    if (year := value(item, "yearpublished")) and year != "0":
        meta["year"] = int(year)
    meta["type"] = ["card"] if "Card Game" in categories else ["board"]
    if categories:
        meta["tags"] = [slugify(c) for c in categories if c != "Card Game"][:6] or None
        if meta["tags"] is None:
            del meta["tags"]
    for key, kind in (("designer", "boardgamedesigner"), ("artist", "boardgameartist")):
        if people := links(kind):
            meta[key] = people
    if publishers := links("boardgamepublisher"):
        meta["publisher"] = publishers[0]
    meta["links"] = {"bgg": f"https://boardgamegeek.com/boardgame/{item.get('id', game_id)}"}
    image = (item.findtext("image") or "").strip()
    return {"meta": meta, "image": image, "names": [n for n in names if n != primary]}


def bgg_search(query: str, token: str | None) -> list[tuple[str, str, str]]:
    root = ET.fromstring(fetch(f"{BGG}/search?query={urllib.parse.quote(query)}&type=boardgame", token))
    out = []
    for item in root.findall("item"):
        name = item.find("name")
        out.append((item.get("id", ""), name.get("value", "") if name is not None else "", value(item, "yearpublished")))
    return out


def yaml_value(v) -> str:
    """One YAML value on one line: scalars quoted only when needed, lists inline ([A, B])."""
    if v is None:
        return ""
    return yaml.safe_dump(v, allow_unicode=True, default_flow_style=True, width=1000).strip().removesuffix("...").strip()


def frontmatter(meta: dict) -> str:
    """YAML frontmatter, one key per line in the given order; maps (links:) nested below their key."""
    lines = ["---"]
    for key, v in meta.items():
        if isinstance(v, dict):
            lines.append(f"{key}:")
            lines += [f"  {k}: {yaml_value(x)}" for k, x in v.items()]
        else:
            lines.append(f"{key}: {yaml_value(v)}".rstrip())
    return "\n".join(lines + ["---", ""])


def skeleton(lang: str) -> str:
    sections = SECTIONS.get(lang) or SECTIONS.get(lang.split("-")[0]) or SECTIONS["en"]
    todo = TODO.get(lang.split("-")[0], TODO["en"])
    return "".join(f"\n# {title} {{#{role}}}\n\n<!-- TODO: {todo} -->\n" for title, role in sections)


def write_game(vault: Vault, slug: str, meta: dict, lang: str, image: str = "", force: bool = False) -> Path:
    folder = vault.root / slug
    path = folder / f"{slug}.game"
    others = [p for p in (path, vault.root / f"{slug}.game") if p.exists()]
    if others and not force:
        raise SystemExit(f"tabula: {others[0]} already exists (use --force to replace it)")
    folder.mkdir(parents=True, exist_ok=True)
    if image:
        try:
            data = fetch(image)
            ext = (Path(urllib.parse.urlparse(image).path).suffix or ".jpg").lower()
            (folder / "media").mkdir(exist_ok=True)
            (folder / "media" / f"box{ext}").write_bytes(data)
            meta = {**meta, "cover": f"media/box{ext}"}
        except BggError as e:
            print(f"tabula: no cover image ({e})", file=sys.stderr)
    if lang != vault.language:
        meta = {**meta, "language": lang}
    path.write_text(frontmatter(meta) + skeleton(lang), encoding="utf-8")
    return path


def cmd_new(args) -> int:
    vault = open_vault(args.vault)
    lang = args.lang or vault.language
    words = args.what
    if words[0] == "bgg" and len(words) >= 2:
        if len(words) > 3:
            raise SystemExit("tabula: use 'tabula new bgg ID [SLUG]'")
        token = args.token or os.environ.get("BGG_TOKEN")
        if not token:
            raise SystemExit("tabula: BoardGameGeek needs a token: register an application at "
                             "https://boardgamegeek.com/applications, then set BGG_TOKEN (or pass --token). "
                             "Without one, use 'tabula new SLUG'.")
        try:
            if not words[1].isdigit():          # a name: show the matching games and their ids
                hits = bgg_search(words[1], token)
                if not hits:
                    print(f"no game called '{words[1]}' on BoardGameGeek", file=sys.stderr)
                    return 1
                print(f"games matching '{words[1]}' (then: tabula new bgg ID):")
                for gid, name, year in hits[:15]:
                    print(f"  {gid:>8}  {name}" + (f" ({year})" if year else ""))
                if len(hits) > 15:
                    print(f"  … {len(hits) - 15} more; be more precise")
                return 0
            found = bgg_game(words[1], token)
        except BggError as e:
            print(f"tabula: {e}", file=sys.stderr)
            return 1
        meta = found["meta"]
        if args.title:
            meta["title"] = args.title
        if args.players:
            meta["players"] = args.players
        slug = words[2] if len(words) == 3 else slugify(meta["title"])
        path = write_game(vault, slug, meta, lang, "" if args.no_cover else found["image"], args.force)
        print(f"wrote {path}")
        if found["names"] and not args.title:
            shown = ", ".join(found["names"][:8]) + (" …" if len(found["names"]) > 8 else "")
            print(f"other names on BoardGameGeek: {shown} (rename with --title, or edit 'title:')")
    else:
        if len(words) != 1:
            raise SystemExit("tabula: use 'tabula new SLUG' or 'tabula new bgg ID [SLUG]'")
        slug = words[0]
        if not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", slug):
            raise SystemExit(f"tabula: '{slug}' isn't a good slug; use lowercase letters, digits and dashes "
                             f"(like '{slugify(slug)}')")
        meta = {"title": args.title or slug.replace("-", " ").capitalize(), "players": args.players}
        path = write_game(vault, slug, meta, lang, force=args.force)
        print(f"wrote {path}")
        if not args.players:
            print("fill in 'players:' (e.g. players: 2-4); 'tabula check' reminds you until it's there")
    print(f"next: write the rules, then 'tabula check {path.stem}' and 'tabula todo {path.stem}'")
    return 0
