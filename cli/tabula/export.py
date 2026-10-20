"""`tabula export`: a self-contained HTML page for one game."""
from __future__ import annotations

import re
import sys
from pathlib import Path

from ._version import __version__
from .syntax import (
    CHOICE_RE, Ctx, ESCAPE_RE, IMAGE_RE, LINK_RE, REF_RE, cond_ok, fold, in_range, open_label,
    parse_choice, parse_range, via_of,
)
from .blocks import Block, is_sep_row
from .filtering import filter_blocks, section_end, section_names, select_key, select_sections
from .vault import Game, open_vault
from .terminal import find_section, plain
from .lookup import Entry, lookup_entries
from .cards import card_catalog, card_rows

UI = {
    "en": {"players": "players", "best": "best with {}", "min": "min", "age": "{}+", "toc": "Contents",
           "showing": "Showing", "base": "base game", "no_variants": "no variants", "all": "every extension and variant",
           "legend": "marks what the enabled extensions and variants add or change",
           "only_with": "only with {}", "by": "Design", "art": "Art", "publisher": "Publisher",
           "exported": "Exported with tabula {} on {}.", "players_n": "{} players",
           "card": "card", "count": "count", "ext": "extension", "key": "key rules"},
    "fr": {"players": "joueurs", "best": "idéal à {}", "min": "min", "age": "{} ans et +", "toc": "Sommaire",
           "showing": "Affichage", "base": "jeu de base", "no_variants": "sans variante",
           "all": "toutes les extensions et variantes",
           "legend": "signale ce que les extensions et variantes activées ajoutent ou modifient",
           "only_with": "seulement avec {}", "by": "Auteurs", "art": "Illustrations", "publisher": "Éditeur",
           "exported": "Exporté avec tabula {} le {}.", "players_n": "{} joueurs",
           "card": "carte", "count": "nombre", "ext": "extension", "key": "règles clés"},
    "de": {"players": "Spieler", "best": "am besten zu {}", "min": "Min.", "age": "ab {}", "toc": "Inhalt",
           "showing": "Ansicht", "base": "Grundspiel", "no_variants": "ohne Varianten",
           "all": "alle Erweiterungen und Varianten",
           "legend": "markiert, was die aktiven Erweiterungen und Varianten hinzufügen oder ändern",
           "only_with": "nur mit {}", "by": "Autoren", "art": "Illustration", "publisher": "Verlag",
           "exported": "Exportiert mit tabula {} am {}.", "players_n": "{} Spieler",
           "card": "Karte", "count": "Anzahl", "ext": "Erweiterung", "key": "Kernregeln"},
}


HTML_CSS = r"""
:root{
  --paper:#fbfcfd; --ink:#1d2433; --muted:#5b6475; --rule:#d8dde5; --card:#ffffff; --desk:#eef1f5;
  --term:#0f6e74; --ext:#6b3fa0; --ext-bg:#f4effa; --open:#9a5b00; --open-bg:#fff5e3; --key:#1d2433;
  --serif:"Literata",Georgia,"Iowan Old Style","Palatino Linotype",serif;
  --sans:"Atkinson Hyperlegible",system-ui,"Segoe UI",Roboto,sans-serif;
}
@media (prefers-color-scheme:dark){:root{
  --paper:#15181e; --ink:#e4e7ec; --muted:#9aa3b2; --rule:#2c323d; --card:#1c2028; --desk:#101318;
  --term:#5cc4c9; --ext:#c3a1f0; --ext-bg:#241c33; --open:#f0b55a; --open-bg:#2c2214; --key:#f4f5f7;}}
*{box-sizing:border-box}
html{background:var(--desk)}
body{margin:0;color:var(--ink);background:var(--paper);font:17px/1.62 var(--serif);
  font-feature-settings:"onum","kern";-webkit-text-size-adjust:100%}
.page{display:grid;grid-template-columns:minmax(0,15rem) minmax(0,46rem);gap:3.5rem;justify-content:center;
  max-width:70rem;margin:0 auto;padding:3rem 2rem 5rem}
header.game{grid-column:1/-1;display:grid;grid-template-columns:1fr auto;gap:2rem;align-items:end;
  padding-bottom:1.6rem;border-bottom:2px solid var(--ink)}
header.game h1{font:600 clamp(2.4rem,6vw,3.6rem)/1.02 var(--serif);letter-spacing:-.015em;margin:0 0 .9rem}
.facts{display:flex;flex-wrap:wrap;gap:.45rem;margin:0;padding:0;list-style:none;font:500 .86rem/1 var(--sans)}
.facts li{border:1px solid var(--rule);border-radius:999px;padding:.38rem .7rem;background:var(--card)}
.credits{margin:.9rem 0 0;color:var(--muted);font:.88rem/1.5 var(--sans)}
.credits b{font-weight:600;color:var(--ink)}
.cover{max-width:11rem;max-height:11rem;border-radius:6px;box-shadow:0 1px 0 var(--rule)}
.selection{grid-column:1/-1;margin:-1.5rem 0 0;padding:.75rem 0 0;font:.9rem/1.5 var(--sans);color:var(--muted)}
.selection strong{color:var(--ink);font-weight:600}
nav.toc{position:sticky;top:2rem;align-self:start;font:.92rem/1.45 var(--sans);max-height:calc(100vh - 4rem);overflow:auto}
nav.toc h2{font:600 .95rem/1 var(--sans);margin:0 0 .8rem;color:var(--muted)}
nav.toc ol{list-style:none;margin:0;padding:0}
nav.toc ol ol{padding-left:.9rem;margin:.2rem 0 .4rem;font-size:.88rem}
nav.toc li{margin:.28rem 0}
nav.toc a{color:var(--ink);text-decoration:none;border-left:2px solid transparent;padding-left:.55rem;margin-left:-.6rem;display:block}
nav.toc a:hover,nav.toc a:focus-visible{border-left-color:var(--term);color:var(--term)}
main{min-width:0}
main>*:first-child{margin-top:0}
h2,h3,h4,h5{font-family:var(--serif);line-height:1.2;scroll-margin-top:1.5rem}
main h2{font-size:1.75rem;font-weight:600;margin:3rem 0 1rem;padding-top:.6rem;border-top:1px solid var(--rule)}
main h3{font-size:1.25rem;font-weight:600;margin:2rem 0 .6rem}
main h4,main h5,main h6{font-size:1.05rem;font-weight:600;margin:1.4rem 0 .4rem}
p{margin:0 0 .9rem}
ul,ol{margin:0 0 1rem;padding-left:1.4rem}
li{margin:.25rem 0}
li>ul,li>ol{margin:.25rem 0 .2rem}
ol>li::marker{font:600 .95em var(--sans);color:var(--muted)}
p.key{font-weight:600;padding:.55rem .8rem;border-left:4px solid var(--key);background:var(--card);margin:1rem 0}
p.key::before,li.key::before{content:"★ ";color:var(--open)}
li.key{font-weight:600}
.key-section{border-left:4px solid var(--key);background:var(--card);padding:.2rem 1rem .4rem;margin:1.4rem 0}
.key-section>h2:first-child,.key-section>h3:first-child,.key-section>h4:first-child{margin-top:.6rem}
h2.key::before,h3.key::before,h4.key::before,h5.key::before{content:"★ ";color:var(--open)}
a.ref.section::before{content:"→ ";color:var(--muted)}
aside.note{margin:.8rem 0 1rem;padding:.5rem .9rem;border-left:2px solid var(--rule);color:var(--muted);font-size:.95rem}
aside.note p{margin:0}
a{color:var(--term)}
a.ref{color:var(--term);text-decoration:underline dotted 1.5px;text-underline-offset:.18em}
a.ref:hover{text-decoration-style:solid}
span.ref{border-bottom:1px dotted var(--muted)}
code{font-size:.9em}
pre{background:var(--card);border:1px solid var(--rule);padding:.8rem 1rem;overflow:auto;border-radius:4px}
figure{margin:1.2rem 0}
figure img{max-width:100%;border-radius:4px}
figcaption{font:.85rem var(--sans);color:var(--muted);margin-top:.35rem}
table{border-collapse:collapse;margin:.6rem 0 1.2rem;font:.92rem/1.4 var(--sans)}
th,td{padding:.4rem .8rem .4rem 0;text-align:left;border-bottom:1px solid var(--rule);vertical-align:top}
th{font-weight:600;border-bottom:2px solid var(--ink)}
td:not(:first-child),th:not(:first-child){font-variant-numeric:tabular-nums}
.badge{display:inline-block;font:600 .74rem/1 var(--sans);padding:.22rem .42rem;border-radius:4px;
  vertical-align:.12em;margin-right:.35rem;white-space:nowrap}
.badge.open{color:var(--open);background:var(--open-bg);border:1px solid currentColor}
.badge.ext{color:#fff;background:var(--ext)}
.badge.opt{color:var(--ext);background:var(--ext-bg);border:1px solid currentColor}
@media (prefers-color-scheme:dark){.badge.ext{color:#15181e}}
.from-ext{color:var(--ext)}
p.from-ext,aside.from-ext,table.from-ext{border-left:3px solid var(--ext);padding-left:.8rem}
li.from-ext::marker{color:var(--ext)}
mark.chosen{background:var(--ext-bg);color:var(--ext);padding:0 .15em;border-radius:3px}
.choice{font-family:var(--sans);font-size:.92em;white-space:nowrap}
.choice .alt{border:1px solid var(--open);border-radius:4px;padding:0 .3em;margin:0 .1em;color:var(--ink)}
.choice .alt b{color:var(--open);font-weight:600;margin-right:.25em}
.choice .alt b.opt{color:var(--ext)}
/* glossary entries as playing cards */
nav.site{grid-column:1/-1;display:flex;flex-wrap:wrap;gap:.4rem 1.2rem;margin:-1.5rem 0 -1.5rem;
  font:.9rem/1.4 var(--sans)}
nav.site a{color:var(--term);text-decoration:none}
nav.site a:hover{text-decoration:underline}
nav.site .here{color:var(--muted)}
.cards{columns:2 17rem;column-gap:.9rem;margin:1rem 0 1.6rem}
hr.end{border:0;border-top:1px solid var(--rule);width:4rem;margin:1.6rem auto}
.card{position:relative;display:inline-block;width:100%;margin:0 0 .9rem;background:var(--card);
  border:1px solid var(--rule);border-radius:11px;padding:.95rem 1.05rem .9rem;font-size:.93rem;line-height:1.5;
  break-inside:avoid;scroll-margin-top:1.5rem}
.card>h3{font:700 1rem/1.25 var(--sans);margin:0 0 .55rem;padding-right:1.6rem}
.card>h3 .badge{float:right;margin:0 -0.3rem 0 .4rem}
.card p:last-child,.card ul:last-child,.card ol:last-child,.card>:last-child{margin-bottom:0}
.card ul,.card ol{padding-left:1.1rem}
.card h4,.card h5{font:600 .93rem/1.3 var(--sans);margin:.9rem 0 .3rem}
.card.ext{border-color:color-mix(in srgb,var(--ext) 45%,var(--rule))}
.card.ext::after{content:"";position:absolute;top:0;right:0;width:1.7rem;height:1.7rem;
  background:linear-gradient(225deg,var(--ext) 50%,transparent 50%);border-top-right-radius:10px}
.card.wide{column-span:all}
table.catalog{width:100%}
table.catalog td:first-child{font-weight:700}
.fields{display:flex;flex-wrap:wrap;gap:.3rem;list-style:none;margin:-.15rem 0 .6rem;padding:0;font:.78rem/1.2 var(--sans)}
.fields li{margin:0;padding:.2rem .45rem;border-radius:4px;background:var(--desk);font-weight:700}
.fields li span{font-weight:400;color:var(--muted)}
.card:target{outline:3px solid var(--term);outline-offset:2px}
.card .from-ext{color:inherit}
footer{grid-column:1/-1;border-top:1px solid var(--rule);padding-top:1rem;color:var(--muted);font:.82rem var(--sans)}
:focus-visible{outline:2px solid var(--term);outline-offset:2px}
@media (max-width:60rem){
  .page{grid-template-columns:minmax(0,1fr);gap:2rem;padding:1.6rem 1.1rem 4rem}
  header.game{grid-template-columns:1fr}
  .cover{max-width:7rem}
  nav.toc{position:static;max-height:none;border:1px solid var(--rule);border-radius:8px;padding:.9rem 1rem;background:var(--card)}
  .selection{margin-top:-1rem}
}
@media print{
  html,body{background:#fff;color:#000}
  :root{--ink:#000;--muted:#444;--rule:#bbb;--card:#fff;--term:#000;--paper:#fff}
  body{font-size:10.5pt}
  .page{display:block;padding:0;max-width:none}
  nav.toc{display:none}
  a.ref{text-decoration:none;border-bottom:.5pt dotted #777}
  main h2{break-after:avoid;margin-top:1.6rem}
  .cards{columns:2;column-gap:6pt}
  .card{border-color:#999;padding:6pt 8pt}
  table,figure,p.key{break-inside:avoid}
}
@media (prefers-reduced-motion:no-preference){html{scroll-behavior:smooth}}
"""


def html_slug(text: str) -> str:
    s = fold(text).replace("'", "")
    return re.sub(r"[^\w]+", "-", s).strip("-") or "section"


class HtmlRenderer:
    def __init__(self, game: Game, blocks: list[Block], ctx: Ctx, key_only: bool = False):
        import html as _html
        self.esc = _html.escape
        self.game, self.blocks, self.ctx, self.key_only = game, blocks, ctx, key_only
        self.game_href = "{}.html"             # where [text](game:slug) links point; `tabula site` changes it
        self.lang = game.language if game.language in UI else game.language.split("-")[0]
        self.t = UI.get(self.lang, UI["en"])
        self.ids: set[str] = set()
        self.toc: list[tuple[int, str, str]] = []
        # every term of the game, and which ones are actually on this page
        self.entries = {fold(e.name): e for e in lookup_entries(game.blocks)}
        shown = lookup_entries(blocks)
        self.anchor = {fold(e.name): ("t-" if e.kind == "definition" else "c-") + html_slug(e.name) for e in shown}
        self.tip = {k: self._tooltip(e) for k, e in self.entries.items()}
        self.heading_ids: dict[int, str] = {}               # id(heading) -> its HTML id, for [[#Section]] links
        for b in blocks:
            if b.kind == "heading" and not b.reopens:
                self.heading_ids[id(b)] = self.uid(
                    b.roles[0] if b.roles else html_slug(plain(CHOICE_RE.sub("", b.text), ctx)))
        self.catalogs: dict[int, list[dict]] = {}          # id(#cards heading) -> its cards
        for c in card_catalog(blocks):
            if c["catalog"] is not None:
                self.catalogs.setdefault(id(c["catalog"]), []).append(c)

    # ------------------------------------------------------------------ helpers
    def uid(self, base: str) -> str:
        i, cand = 1, base
        while cand in self.ids:
            i += 1
            cand = f"{base}-{i}"
        self.ids.add(cand)
        return cand

    def _tooltip(self, e: "Entry") -> str:
        texts = []
        for b in e.blocks:
            for k in (b.children if b.kind == "def" else [b]):
                if k.text:
                    texts.append(plain(k.text, self.ctx))
        tip = " ".join(texts)
        return tip[:220] + ("…" if len(tip) > 220 else "")

    def data_uri(self, src: str) -> str:
        import base64
        import mimetypes
        if re.match(r"^[a-z]+://", src):
            return src
        p = self.game.base_dir / src
        if not p.exists():
            return src
        mime = mimetypes.guess_type(p.name)[0] or "application/octet-stream"
        return f"data:{mime};base64," + base64.b64encode(p.read_bytes()).decode()

    def label_badges(self, label: str) -> str:
        """Undecided condition codes: player counts in amber, extensions/variants in violet."""
        toks = label.split()
        opts = [t for t in toks if t[:1] in "+-"]
        counts = [t for t in toks if t not in opts]
        out = f'<span class="badge open">{self.esc(" ".join(counts))}</span>' if counts else ""
        return out + (f'<span class="badge opt">{self.esc(" ".join(opts))}</span>' if opts else "")

    def badges(self, b: Block) -> str:
        out = ""
        if lab := open_label(b.cond, self.ctx):
            out += self.label_badges(lab)
        if b.via:
            out += f'<span class="badge ext">+{self.esc(" +".join(b.via))}</span>'
        return out

    # ------------------------------------------------------------------ inline
    def inline(self, text: str) -> str:
        stash: list[str] = []

        def keep(h: str) -> str:
            stash.append(h)
            return f"\x00{len(stash) - 1}\x00"

        text = ESCAPE_RE.sub(lambda m: keep(self.esc(m.group(1))), text)
        text = CHOICE_RE.sub(lambda m: keep(self.choice(m)), text)
        text = REF_RE.sub(lambda m: keep(self.ref(m.group(1).strip(), (m.group(2) or m.group(1).lstrip("#")).strip())), text)
        text = IMAGE_RE.sub(lambda m: keep(f'<img src="{self.esc(self.data_uri(m.group(2)))}" alt="{self.esc(m.group(1))}">'), text)
        text = LINK_RE.sub(lambda m: keep(self.link(m.group(1), m.group(2))), text)
        text = re.sub(r"`([^`]+)`", lambda m: keep(f"<code>{self.esc(m.group(1))}</code>"), text)
        text = self.esc(text, quote=False)
        text = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", text)
        text = re.sub(r"(?<!\w)__(?!\s)(.+?)(?<!\s)__(?!\w)", r"<strong>\1</strong>", text)
        text = re.sub(r"(?<![*\w])\*(?!\s)(.+?)(?<!\s)\*(?![*\w])", r"<em>\1</em>", text)
        text = re.sub(r"(?<!\w)_(?!\s)(.+?)(?<!\s)_(?!\w)", r"<em>\1</em>", text)
        while "\x00" in text:
            text = re.sub(r"\x00(\d+)\x00", lambda m: stash[int(m.group(1))], text)
        return text

    def choice(self, m) -> str:
        branches = parse_choice(m.group(1))
        if branches is None:
            return self.esc(m.group(0))
        ctx = self.ctx
        remaining = [(c, t, any(k == "*" for k, _, _ in c.tokens)) for c, t in branches]
        remaining = [(c, t, star) for c, t, star in remaining if star or cond_ok(c, ctx)]
        concrete = [(c, t) for c, t, star in remaining if not star]
        if concrete:
            c, t = concrete[0]
            if not open_label(c, ctx):
                inner = self.inline(t)
                return f'<mark class="chosen" title="+{self.esc(" +".join(via_of(c, ctx)))}">{inner}</mark>' \
                    if via_of(c, ctx) else inner
            def lab(c, star):
                text = "*" if star else open_label(c, ctx)
                return f'<b class="opt">{self.esc(text)}</b>' if text[:1] in "+-" else f"<b>{self.esc(text)}</b>"
            alts = "".join(f'<span class="alt">{lab(c, star)}{self.inline(t)}</span>' for c, t, star in remaining)
            return f'<span class="choice">{alts}</span>'
        return next((self.inline(t) for _, t, star in remaining if star), "")

    def ref(self, name: str, shown: str) -> str:
        if name.startswith("#"):
            target = find_section(self.blocks, name)
            if target is not None and id(target) in self.heading_ids:
                return f'<a class="ref section" href="#{self.heading_ids[id(target)]}">{self.esc(shown)}</a>'
            return f'<span class="ref section">{self.esc(shown)}</span>'      # not on this page
        k = fold(name)
        tip = self.tip.get(k, "")
        if k in self.anchor:
            return f'<a class="ref" href="#{self.anchor[k]}" title="{self.esc(tip)}">{self.esc(shown)}</a>'
        e = self.entries.get(k)
        if e and e.cond:
            tip = self.t["only_with"].format(e.cond.raw)
        return f'<span class="ref" title="{self.esc(tip)}">{self.esc(shown)}</span>'

    def link(self, label: str, href: str) -> str:
        if href.startswith("game:"):
            href = self.game_href.format(href[5:])
        return f'<a href="{self.esc(href)}">{self.esc(label)}</a>'

    # ------------------------------------------------------------------ blocks
    def render(self, blocks: list[Block], in_card: bool = False) -> str:
        out: list[str] = []
        lists: list[tuple[int, str]] = []          # open lists: (indent, "ul"/"ol")
        counters: dict[int, int] = {}
        k = 0

        def close_lists(to_level: int = -1):
            while lists and lists[-1][0] > to_level:
                out.append(f"</li></{lists.pop()[1]}>")

        while k < len(blocks):
            b = blocks[k]
            nested = b.kind in ("note", "table", "para", "key") and b.level and lists
            if b.kind == "item":
                while lists and lists[-1][0] > b.level:
                    out.append(f"</li></{lists.pop()[1]}>")
                    counters = {l: n for l, n in counters.items() if l <= b.level}
                tag = "ol" if b.ordered else "ul"
                if lists and lists[-1][0] == b.level:
                    out.append("</li>")
                else:
                    out.append(f"<{tag}>")
                    lists.append((b.level, tag))
                attrs, cls = "", []
                if b.ordered:
                    counters[b.level] = counters.get(b.level, b.start - 1) + 1
                    attrs += f' value="{counters[b.level]}"'
                if b.key:
                    cls.append("key")
                if b.tint or b.via:
                    cls.append("from-ext")
                if b.qty and (rm := REF_RE.search(b.text)):
                    a = self.anchor.get(fold(rm.group(1)), "")
                    if a.startswith("c-"):
                        attrs += f' id="{self.uid(a)}"'
                if cls:
                    attrs += f' class="{" ".join(cls)}"'
                out.append(f"<li{attrs}>{self.badges(b)}{self.inline(b.text)}")
                k += 1
                continue
            if not nested:
                close_lists()
                counters = {}
            if b.kind == "heading" and b.key:      # a key section: framed with everything under it
                end = section_end(blocks, k)
                out.append('<section class="key-section">' + self.block(b, in_card)
                           + self.render(blocks[k + 1:end], in_card) + "</section>")
                k = end
                continue
            if b.kind == "def":
                group = []
                while k < len(blocks) and blocks[k].kind == "def":
                    group.append(blocks[k])
                    k += 1
                out.append('<div class="cards">' + "".join(self.card(d) for d in group) + "</div>")
                continue
            out.append(self.block(b, in_card))
            k += 1
        close_lists()
        return "\n".join(out)

    def card(self, d: Block) -> str:
        cid = self.uid(self.anchor.get(fold(d.term), "t-" + html_slug(d.term)))
        from_ext = bool(d.via) or (self.ctx.everything and d.cond is not None and
                                   any(k == "v" and not neg for k, neg, _ in d.cond.tokens))
        cls = "card" + (" ext" if from_ext else "")
        size = sum(len(c.text) for c in d.children) + 120 * sum(1 for c in d.children if c.kind == "heading")
        if size > 900:
            cls += " wide"
        chips = ""
        shown = {k: self.inline(v) for k, v in d.fields.items()}
        shown = {k: v for k, v in shown.items() if re.sub(r"<[^>]+>", "", v).strip()}
        if shown:
            chips = '<ul class="fields">' + "".join(
                f'<li><span>{self.esc(k)}</span> {v}</li>' for k, v in shown.items()) + "</ul>"
        return (f'<article class="{cls}" id="{cid}"><h3>{self.badges(d)}{self.inline(d.term)}</h3>{chips}'
                f'{self.render(d.children, in_card=True)}</article>')

    def block(self, b: Block, in_card: bool) -> str:
        ext = " from-ext" if (b.via or b.tint) else ""
        if b.kind == "heading" and b.reopens:
            return "" if b.quiet else '<hr class="end">'
        if b.kind == "heading":
            level = min(6, b.level + (3 if in_card else 1))
            title = self.inline(b.text)
            hid = self.heading_ids.get(id(b)) or self.uid(
                b.roles[0] if b.roles else html_slug(plain(CHOICE_RE.sub("", b.text), self.ctx)))
            if not in_card and b.level <= 2:
                self.toc.append((b.level, hid, title))
            cls = ' class="key"' if b.key else ""
            head = f'<h{level} id="{hid}"{cls}>{self.badges(b)}{title}</h{level}>'
            if not in_card and id(b) in self.catalogs:
                head += self.catalog_table(self.catalogs[id(b)])
            return head
        if b.kind == "para":
            return f'<p class="{ext.strip()}">{self.badges(b)}{self.inline(b.text)}</p>' if ext else \
                f"<p>{self.badges(b)}{self.inline(b.text)}</p>"
        if b.kind == "key":
            return f'<p class="key{ext}">{self.badges(b)}{self.inline(b.text)}</p>'
        if b.kind == "note":
            return f'<aside class="note{ext}"><p>{self.badges(b)}{self.inline(b.text)}</p></aside>'
        if b.kind == "image":
            return (f'<figure><img src="{self.esc(self.data_uri(b.term))}" alt="{self.esc(b.text)}">'
                    f'<figcaption>{self.inline(b.text)}</figcaption></figure>')
        if b.kind == "code":
            return f"<pre><code>{self.esc(b.text)}</code></pre>"
        if b.kind == "table":
            return self.table(b)
        return ""

    def catalog_table(self, catalog: list[dict]) -> str:
        cols, rows = card_rows(catalog, self.blocks, self.ctx)
        if len(cols) == 1:                      # no counts or fields: the cards themselves are enough
            return ""
        head = "".join(f"<th>{self.esc(self.t.get(c, c))}</th>" for c in cols)
        body = []
        for r in rows:
            cells = []
            for c in cols:
                v = str(r.get(c, ""))
                if c == "card":
                    a = self.anchor.get(fold(v))
                    cells.append(f'<td><a class="ref" href="#{a}">{self.esc(v)}</a></td>' if a else f"<td>{self.esc(v)}</td>")
                elif c == "ext":
                    badge = (self.label_badges(v) if self.ctx.everything
                             else f'<span class="badge ext">{self.esc(v)}</span>') if v else ""
                    cells.append(f"<td>{badge}</td>")
                else:
                    cells.append(f"<td>{self.inline(v)}</td>")
            body.append("<tr>" + "".join(cells) + "</tr>")
        return f'<table class="catalog"><thead><tr>{head}</tr></thead><tbody>{"".join(body)}</tbody></table>'

    def table(self, b: Block) -> str:
        rows = [cells for _, cells in b.rows if not is_sep_row(cells)]
        if not rows:
            return ""

        def cell(c: str, tag: str) -> str:
            pre = ""
            if (lm := re.match(r"\x02(.*?)\x02", c)):
                pre, c = self.label_badges(lm.group(1)), c[lm.end():]
            if (vm := re.match(r"\x01(.*?)\x01", c)):
                pre, c = pre + f'<span class="badge ext">+{self.esc(vm.group(1).replace(",", " +"))}</span>', c[vm.end():]
            return f"<{tag}>{pre}{self.inline(c)}</{tag}>"

        head = "<tr>" + "".join(cell(c, "th") for c in rows[0]) + "</tr>"
        body = "".join("<tr>" + "".join(cell(c, "td") for c in r) + "</tr>" for r in rows[1:])
        return f"<table><thead>{head}</thead><tbody>{body}</tbody></table>"

    # ------------------------------------------------------------------ page
    def page(self, title_suffix: str = "", nav: str = "") -> str:
        """The full HTML document. `nav`: links shown above the title (used by `tabula site`)."""
        g, t, esc, ctx = self.game, self.t, self.esc, self.ctx
        body = self.render(self.blocks)          # fills self.toc
        meta = g.meta
        facts = []
        if meta.get("players") is not None:
            facts.append(f"{esc(str(meta['players']).replace('-', '–'))} {t['players']}")
        if meta.get("best_players") is not None:
            facts.append(esc(t["best"].format(meta["best_players"])))
        if meta.get("duration") is not None:
            facts.append(f"{esc(str(meta['duration']).replace('-', '–'))} {t['min']}")
        if meta.get("age") is not None:
            facts.append(esc(t["age"].format(str(meta["age"]).rstrip("+"))))
        credits = []
        for key, label in (("designer", "by"), ("artist", "art"), ("publisher", "publisher")):
            v = meta.get(key)
            if v:
                names = ", ".join(map(str, v)) if isinstance(v, list) else str(v)
                credits.append(f"<b>{t[label]}</b> {esc(names)}")
        cover = ""
        if meta.get("cover") and (g.base_dir / str(meta["cover"])).exists():
            cover = f'<img class="cover" src="{esc(self.data_uri(str(meta["cover"])))}" alt="">'

        sel = [t["key"]] if self.key_only else []
        if ctx.players is not None:
            sel.append(t["players_n"].format(ctx.players))
        if ctx.everything:
            if g.options:
                sel.append(t["all"])
        else:
            sel += [f"+{v}" for v in sorted(ctx.variants)]
            if g.extensions and not (ctx.variants & {k.lower() for k in g.extensions}):
                sel.append(t["base"])
            if g.variants and not (ctx.variants & {k.lower() for k in g.variants}):
                sel.append(t["no_variants"])
        selection = ""
        if sel:
            selection = f'<p class="selection"><strong>{t["showing"]}:</strong> {esc(", ".join(sel))}'
            if ctx.variants and not ctx.everything:
                selection += f'<br><span class="badge ext">+…</span>{esc(t["legend"])}'
            selection += "</p>"

        toc = ""
        if self.toc:
            items, open_sub = [], False
            for level, hid, title in self.toc:
                title_txt = re.sub(r"<[^>]+>", "", title)
                if level == 1:
                    if open_sub:
                        items.append("</ol></li>")
                        open_sub = False
                    elif items:
                        items.append("</li>")
                    items.append(f'<li><a href="#{hid}">{title_txt}</a>')
                else:
                    if not open_sub:
                        items.append("<ol>")
                        open_sub = True
                    items.append(f'<li><a href="#{hid}">{title_txt}</a></li>')
            items.append("</ol></li>" if open_sub else "</li>")
            toc = f'<nav class="toc" aria-label="{t["toc"]}"><h2>{t["toc"]}</h2><ol>{"".join(items)}</ol></nav>'
        import datetime
        footer = t["exported"].format(__version__, datetime.date.today().isoformat())
        fonts = ('<link rel="preconnect" href="https://fonts.googleapis.com">'
                 '<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Atkinson+Hyperlegible:wght@400;700'
                 '&family=Literata:opsz,wght@7..72,400;7..72,600;7..72,700&display=swap">')
        return f"""<!doctype html>
<html lang="{esc(g.language)}">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{esc(g.title)}{esc(title_suffix)}</title>
{fonts}
<style>{HTML_CSS}</style>
</head>
<body>
<div class="page">
{f'<nav class="site">{nav}</nav>' if nav else ""}
<header class="game"><div><h1>{esc(g.title)}</h1>
<ul class="facts">{"".join(f"<li>{f}</li>" for f in facts)}</ul>
{f'<p class="credits">{" &nbsp; ".join(credits)}</p>' if credits else ""}</div>{cover}</header>
{selection}
{toc}
<main>
{body}
</main>
<footer>{esc(footer)}</footer>
</div>
</body>
</html>
"""


def export_name(game: Game, ctx: Ctx, sections, key: bool = False) -> str:
    parts = [game.slug]
    if ctx.players is not None:
        parts.append(f"{ctx.players}p")
    if ctx.everything:
        parts.append("all")
    parts += sorted(ctx.variants)
    if sections:
        parts += [html_slug(s) for s in sections]
    if key:
        parts.append("key")
    name = "-".join(parts)
    if game.language != game.default_language:
        name += f".{game.language}"
    return name + ".html"


def cmd_export(args) -> int:
    vault = open_vault(args.vault, args.game)
    game = vault.load(vault.find(args.game), args.lang)
    if args.all and (args.ext or args.variant):
        print("tabula: --all already shows every extension and variant; drop either --all or -e/-v", file=sys.stderr)
        return 2
    ctx = Ctx(args.players, {v.lower() for v in (args.variant or []) + (args.ext or [])}, args.all)
    rng = parse_range(game.meta.get("players"))
    if args.players is not None and rng and not in_range(rng, args.players):
        print(f"tabula: {game.title} is for {game.meta.get('players')} players, not {args.players}", file=sys.stderr)
        return 2
    for v in ctx.variants:
        if v not in {k.lower() for k in game.options}:
            print(f"tabula: '{v}' is not a variant or extension of {game.title}", file=sys.stderr)
            return 2
    blocks = filter_blocks(game.blocks, ctx)
    if args.section:
        picked = select_sections(blocks, args.section)
        if not picked:
            print(f"tabula: no section {', '.join(args.section)} in {game.title}; "
                  f"available: {', '.join(section_names(blocks)) or '(none)'}", file=sys.stderr)
            return 2
        blocks = picked
    if args.key:
        blocks = select_key(blocks)
        if not blocks:
            print(f"tabula: no key rules in {game.title} (mark them with '! ' or '## ! Title')", file=sys.stderr)
            return 1
    renderer = HtmlRenderer(game, blocks, ctx, key_only=args.key)
    html_text = renderer.page(f" — {renderer.t['key']}" if args.key else "")
    if args.output == "-":
        sys.stdout.write(html_text)
        return 0
    name = export_name(game, ctx, args.section, key=args.key)
    out = Path(args.output) if args.output else Path.cwd() / name
    if out.is_dir():
        out = out / name
    out.write_text(html_text, encoding="utf-8")
    print(f"wrote {out}")
    if any(i.level == "error" for i in game.issues):
        print(f"tabula: this file has errors; run 'tabula check {game.slug}'", file=sys.stderr)
    return 0
