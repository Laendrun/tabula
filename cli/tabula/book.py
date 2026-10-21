"""`tabula book`: games as an EPUB book, for e-readers, phones and tablets (one game, some, or the whole vault)."""
from __future__ import annotations

import datetime
import html
import re
import sys
import uuid
import zipfile
from html.parser import HTMLParser
from pathlib import Path

from ._version import __version__
from .export import HtmlRenderer, html_slug
from .filtering import filter_blocks, select_key
from .syntax import Ctx, fold, in_range, parse_range
from .vault import Game, open_vault
from .options import players_range

MEDIA_TYPES = {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png", ".gif": "image/gif",
               ".webp": "image/webp", ".svg": "image/svg+xml"}
BOOK_UI = {
    "en": {"games": "Games", "made": "Made with tabula {} on {}.", "key": "key rules", "all": "every extension and variant",
           "players_n": "for {} players", "contents": "Contents"},
    "fr": {"games": "Jeux", "made": "Fait avec tabula {} le {}.", "key": "règles clés",
           "all": "toutes les extensions et variantes", "players_n": "pour {} joueurs", "contents": "Sommaire"},
    "de": {"games": "Spiele", "made": "Erstellt mit tabula {} am {}.", "key": "Kernregeln",
           "all": "alle Erweiterungen und Varianten", "players_n": "für {} Spieler", "contents": "Inhalt"},
}
VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "source", "track", "wbr"}

BOOK_CSS = """
body { font-family: serif; line-height: 1.45; margin: 0 4%; }
h1 { font-size: 1.8em; margin: 0.6em 0 0.2em; line-height: 1.15; }
h2 { font-size: 1.35em; margin: 1.4em 0 0.4em; border-bottom: 1px solid #999; padding-bottom: 0.1em; }
h3 { font-size: 1.1em; margin: 1.1em 0 0.3em; }
h4, h5, h6 { font-size: 1em; margin: 1em 0 0.3em; }
p { margin: 0.4em 0; }
.facts, .credits, .made, .selection { font-family: sans-serif; font-size: 0.85em; color: #444; margin: 0.2em 0; }
img.cover { display: block; max-width: 60%; max-height: 14em; margin: 0.8em auto; }
.badge { font-family: sans-serif; font-size: 0.7em; font-weight: bold; border: 1px solid #888; border-radius: 0.3em;
         padding: 0 0.25em; margin-right: 0.3em; white-space: nowrap; }
p.key, li.key, .key-section { font-weight: bold; }
p.key, .key-section { border-left: 0.25em solid #333; padding-left: 0.5em; }
.key-section { font-weight: normal; }
aside.note { margin: 0.5em 0 0.5em 1em; font-style: italic; }
aside.callout { margin: 0.7em 0; padding: 0.3em 0.6em; border: 1px solid #bbb; border-left: 0.3em solid #333; page-break-inside: avoid; }
aside.callout p { margin: 0.2em 0; }
p.callout-title { font-family: sans-serif; font-weight: bold; font-size: 0.9em; }
.cards { margin: 0.5em 0; }
article.card { border-left: 0.15em solid #999; padding-left: 0.6em; margin: 0.8em 0; page-break-inside: avoid; }
article.card h3 { margin-top: 0; }
ul.fields { list-style: none; padding: 0; margin: 0.2em 0; font-family: sans-serif; font-size: 0.85em; }
ul.fields li span { color: #555; }
table { border-collapse: collapse; margin: 0.6em 0; font-size: 0.9em; }
th, td { border: 1px solid #999; padding: 0.15em 0.4em; text-align: left; vertical-align: top; }
a { color: inherit; }
a.ref { text-decoration: underline; }
.choice .alt { margin-right: 0.9em; }
.choice .alt b { font-family: sans-serif; font-size: 0.75em; margin-right: 0.25em; }
hr.end { border: 0; border-top: 1px solid #999; width: 3em; margin: 1em auto; }
ol.games { padding-left: 1.2em; }
figure { margin: 0.8em 0; text-align: center; }
figure img { max-width: 100%; }
img.sym { height: 1.15em; width: auto; vertical-align: -0.22em; display: inline; }
figcaption { font-size: 0.85em; color: #444; }
pre { white-space: pre-wrap; font-size: 0.85em; }
.image-missing { font-style: italic; color: #555; }
"""


class _Xhtml(HTMLParser):
    """Re-serialise an HTML fragment as well-formed XHTML: void tags closed, attributes quoted, entities as
    characters, unclosed tags closed at the right place."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.out: list[str] = []
        self.open: list[str] = []

    def attrs(self, attrs) -> str:
        return "".join(f' {k}="{html.escape(k if v is None else v, quote=True)}"'
                       for k, v in attrs if re.fullmatch(r"[a-zA-Z_][\w.:-]*", k))

    def handle_starttag(self, tag, attrs):
        if tag == "img":
            a = dict(attrs)
            if not a.get("src") or re.match(r"^[a-z]+://", a["src"]):
                # e-readers don't load images from the web (and a missing image has no file): its caption stays
                if a.get("alt") and "figure" not in self.open:      # a figure keeps its caption anyway
                    self.out.append(f'<span class="image-missing">[{html.escape(a["alt"], quote=False)}]</span>')
                return
        if tag in VOID:
            self.out.append(f"<{tag}{self.attrs(attrs)}/>")
        else:
            self.out.append(f"<{tag}{self.attrs(attrs)}>")
            self.open.append(tag)

    def handle_startendtag(self, tag, attrs):
        self.out.append(f"<{tag}{self.attrs(attrs)}/>")

    def handle_endtag(self, tag):
        if tag in VOID or tag not in self.open:
            return
        while self.open:
            t = self.open.pop()
            self.out.append(f"</{t}>")
            if t == tag:
                break

    def handle_data(self, data):
        self.out.append(html.escape(data, quote=False))

    def result(self) -> str:
        self.close()
        while self.open:
            self.out.append(f"</{self.open.pop()}>")
        return "".join(self.out)


def to_xhtml(fragment: str) -> str:
    p = _Xhtml()
    p.feed(fragment)
    return p.result()


def xhtml_page(title: str, lang: str, body: str) -> str:
    return (f'<?xml version="1.0" encoding="UTF-8"?>\n<!DOCTYPE html>\n'
            f'<html xmlns="http://www.w3.org/1999/xhtml" xmlns:epub="http://www.idpf.org/2007/ops" '
            f'lang="{lang}" xml:lang="{lang}">\n<head>\n<meta charset="UTF-8"/>\n<title>{html.escape(title)}</title>\n'
            f'<link rel="stylesheet" type="text/css" href="style.css"/>\n</head>\n<body>\n{body}\n</body>\n</html>\n')


class Book:
    """Collects the chapters and images, then writes the .epub."""

    def __init__(self, title: str, lang: str):
        self.title, self.lang = title, lang
        self.chapters: list[dict] = []          # {file, title, body, toc: [(level, id, title)]}
        self.images: dict[Path, str] = {}       # source file -> name inside the book (images/…)

    def image(self, path: Path) -> str:
        """Add an image file to the book; returns its href from a chapter."""
        path = path.resolve()
        if path not in self.images:
            ext = path.suffix.lower()
            if ext not in MEDIA_TYPES or not path.is_file():
                return ""
            base = re.sub(r"[^a-z0-9-]+", "-", path.stem.lower()).strip("-") or "image"
            name, n = f"{base}{ext}", 1
            while name in self.images.values():
                n += 1
                name = f"{base}-{n}{ext}"
            self.images[path] = name
        return f"images/{self.images[path]}"

    def unlink_missing(self, body: str) -> str:
        """Links to a game that isn't in this book become plain text."""
        files = {ch["file"] for ch in self.chapters}

        def fix(m):
            return m.group(0) if m.group(2) in files else f"<span{m.group(1)}{m.group(4)}>{m.group(5)}</span>"
        return re.sub(r'<a((?:\s(?!href)[\w:-]+="[^"]*")*)\shref="([^"#/:]+\.xhtml)(#[^"]*)?"([^>]*)>(.*?)</a>',
                      fix, body, flags=re.S)

    def write(self, out: Path, ident: str, title_page: str) -> None:
        now = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        esc = html.escape
        manifest = ['<item id="nav" href="nav.xhtml" media-type="application/xhtml+xml" properties="nav"/>',
                    '<item id="ncx" href="toc.ncx" media-type="application/x-dtbncx+xml"/>',
                    '<item id="css" href="style.css" media-type="text/css"/>',
                    '<item id="title" href="title.xhtml" media-type="application/xhtml+xml"/>']
        spine = ['<itemref idref="title"/>']
        for i, ch in enumerate(self.chapters):
            manifest.append(f'<item id="c{i}" href="{ch["file"]}" media-type="application/xhtml+xml"/>')
            spine.append(f'<itemref idref="c{i}"/>')
        for i, (src, name) in enumerate(self.images.items()):
            manifest.append(f'<item id="i{i}" href="images/{name}" media-type="{MEDIA_TYPES[Path(name).suffix]}"/>')
        opf = f'''<?xml version="1.0" encoding="UTF-8"?>
<package xmlns="http://www.idpf.org/2007/opf" version="3.0" unique-identifier="bookid" xml:lang="{self.lang}">
  <metadata xmlns:dc="http://purl.org/dc/elements/1.1/">
    <dc:identifier id="bookid">{ident}</dc:identifier>
    <dc:title>{esc(self.title)}</dc:title>
    <dc:language>{self.lang}</dc:language>
    <dc:creator>tabula</dc:creator>
    <meta property="dcterms:modified">{now}</meta>
  </metadata>
  <manifest>
    {chr(10).join("    " + m for m in manifest).strip()}
  </manifest>
  <spine toc="ncx">
    {chr(10).join("    " + s for s in spine).strip()}
  </spine>
</package>
'''

        def nav_items(ch) -> str:
            subs = [(hid, t) for level, hid, t in ch["toc"] if level == 1]
            inner = "".join(f'<li><a href="{ch["file"]}#{hid}">{esc(t)}</a></li>' for hid, t in subs)
            return f'<li><a href="{ch["file"]}">{esc(ch["title"])}</a>' + (f"<ol>{inner}</ol>" if inner else "") + "</li>"

        contents = BOOK_UI.get(self.lang, BOOK_UI["en"])["contents"]
        nav = xhtml_page(self.title, self.lang,
                         f'<nav epub:type="toc" id="toc"><h1>{esc(contents)}</h1><ol>'
                         f'<li><a href="title.xhtml">{esc(self.title)}</a></li>'
                         + "".join(nav_items(ch) for ch in self.chapters) + "</ol></nav>")
        points, order = [], 1
        for ch in self.chapters:
            sub = []
            for level, hid, t in ch["toc"]:
                if level == 1:
                    order += 1
                    sub.append(f'<navPoint id="n{order}" playOrder="{order}"><navLabel><text>{esc(t)}</text></navLabel>'
                               f'<content src="{ch["file"]}#{hid}"/></navPoint>')
            order += 1
            points.append(f'<navPoint id="g{order}" playOrder="{order}"><navLabel><text>{esc(ch["title"])}</text>'
                          f'</navLabel><content src="{ch["file"]}"/>{"".join(sub)}</navPoint>')
        ncx = (f'<?xml version="1.0" encoding="UTF-8"?>\n<ncx xmlns="http://www.daisy.org/z3986/2005/ncx/" '
               f'version="2005-1"><head><meta name="dtb:uid" content="{ident}"/></head>'
               f'<docTitle><text>{esc(self.title)}</text></docTitle><navMap>'
               f'<navPoint id="t1" playOrder="1"><navLabel><text>{esc(self.title)}</text></navLabel>'
               f'<content src="title.xhtml"/></navPoint>{"".join(points)}</navMap></ncx>\n')
        container = ('<?xml version="1.0" encoding="UTF-8"?>\n<container version="1.0" '
                     'xmlns="urn:oasis:names:tc:opendocument:xmlns:container"><rootfiles>'
                     '<rootfile full-path="OEBPS/content.opf" media-type="application/oebps-package+xml"/>'
                     '</rootfiles></container>\n')
        with zipfile.ZipFile(out, "w") as z:
            z.writestr(zipfile.ZipInfo("mimetype"), "application/epub+zip", compress_type=zipfile.ZIP_STORED)
            files = {"META-INF/container.xml": container, "OEBPS/content.opf": opf, "OEBPS/nav.xhtml": nav,
                     "OEBPS/toc.ncx": ncx, "OEBPS/style.css": BOOK_CSS, "OEBPS/title.xhtml": title_page}
            for ch in self.chapters:
                files[f"OEBPS/{ch['file']}"] = xhtml_page(ch["title"], ch["lang"], self.unlink_missing(ch["body"]))
            for name, text in files.items():
                z.writestr(name, text, compress_type=zipfile.ZIP_DEFLATED)
            for src, name in self.images.items():
                z.write(src, f"OEBPS/images/{name}", compress_type=zipfile.ZIP_DEFLATED)


def chapter(book: Book, game: Game, ctx: Ctx, key: bool) -> dict | None:
    blocks = filter_blocks(game.blocks, ctx)
    if key:
        blocks = select_key(blocks)
        if not blocks:
            return None
    r = HtmlRenderer(game, blocks, ctx, key_only=key)
    r.game_href = "{}.xhtml"
    r.image_src = book.image
    body = r.render(blocks)                         # fills r.toc
    esc = html.escape
    head = [f'<h1 id="top">{esc(game.title)}</h1>']
    if facts := r.facts():
        head.append(f'<p class="facts">{" · ".join(facts)}</p>')
    if credits := r.credits():
        head.append(f'<p class="credits">{" · ".join(credits)}</p>')
    if game.cover and game.cover.is_file() and (src := book.image(game.cover)):
        head.append(f'<img class="cover" src="{src}" alt=""/>')
    return {"file": f"{game.slug}.xhtml", "title": game.title, "lang": game.language,
            "body": to_xhtml("\n".join(head) + "\n" + body), "toc": r.toc}


def cmd_book(args) -> int:
    vault = open_vault(args.vault, args.games[0] if args.games else None)
    paths = [vault.find(g) for g in args.games] if args.games else vault.discover()
    if not paths:
        print(f"tabula: no games in {vault.root}", file=sys.stderr)
        return 1
    if args.all and (args.ext or args.variant):
        print("tabula: --all already includes every extension and variant; drop either --all or -e/-v", file=sys.stderr)
        return 2
    chosen = {v.lower() for v in (args.variant or []) + (args.ext or [])}
    ctx = Ctx(args.players, chosen, not chosen)         # without -e/-v: everything, marked with badges
    lang = args.lang or vault.language
    games = [vault.load(p, lang) for p in paths]
    skipped = []
    if args.players is not None:
        keep = []
        for g in games:
            rng = players_range(g, {c for c in chosen}, everything=not chosen)   # with the extensions in the book
            (keep if not rng or in_range(rng, args.players) else skipped).append(g)
        games = keep
    games.sort(key=lambda g: fold(g.title))
    single = len(paths) == 1 and args.games
    title = args.title or (games[0].title if single and games else str(vault.config.get("name") or vault.root.name))
    ui = BOOK_UI.get(lang.split("-")[0], BOOK_UI["en"])
    if args.key and not args.title:
        title = f"{title} — {ui['key']}"
    book = Book(title, lang)
    for g in games:
        for v in chosen - {k.lower() for k in g.options}:
            if len(games) == 1:
                print(f"tabula: '{v}' is not a variant or extension of {g.title}", file=sys.stderr)
                return 2
        ch = chapter(book, g, ctx, args.key)
        if ch:
            book.chapters.append(ch)
        else:
            skipped.append(g)
    if not book.chapters:
        print("tabula: nothing to put in the book" + (" (no key rules)" if args.key else ""), file=sys.stderr)
        return 1
    esc = html.escape
    sel = [ui["players_n"].format(args.players)] if args.players is not None else []
    sel += [f"+{v}" for v in sorted(chosen)] if chosen else [ui["all"]]
    items = "".join(f'<li><a href="{ch["file"]}">{esc(ch["title"])}</a></li>' for ch in book.chapters)
    today = datetime.date.today().isoformat()
    title_page = xhtml_page(title, lang,
                            f'<h1>{esc(title)}</h1>\n<p class="selection">{esc(", ".join(sel))}</p>\n'
                            + (f'<h2>{esc(ui["games"])}</h2>\n<ol class="games">{items}</ol>\n' if len(book.chapters) > 1 else "")
                            + f'<p class="made">{esc(ui["made"].format(__version__, today))}</p>')
    name = (games[0].slug if single else html_slug(str(vault.config.get("name") or vault.root.name)))
    parts = [name] + ([f"{args.players}p"] if args.players is not None else []) + sorted(chosen) + (["key"] if args.key else [])
    out = Path(args.output) if args.output else Path.cwd() / ("-".join(parts) + ".epub")
    if out.is_dir():
        out = out / ("-".join(parts) + ".epub")
    ident = "urn:uuid:" + str(uuid.uuid5(uuid.NAMESPACE_URL, f"tabula:{vault.root}:{'-'.join(parts)}"))
    book.write(out, ident, title_page)
    print(f"wrote {out} ({len(book.chapters)} game{'s' if len(book.chapters) != 1 else ''})")
    if skipped:
        print(f"left out: {', '.join(g.title for g in skipped)}"
              + (f" (not for {args.players} players, or no key rules)" if args.players is not None or args.key else ""),
              file=sys.stderr)
    return 0
