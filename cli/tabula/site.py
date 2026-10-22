"""`tabula site`: the whole vault as a small static website (an index page and a page per game)."""
from __future__ import annotations

import html
import json
import math
import re
import shutil
import sys
from pathlib import Path

from .export import HTML_CSS, HtmlRenderer
from .filtering import filter_blocks, select_key, select_turn
from .syntax import Ctx, fold, in_range, parse_range
from .vault import Game, Vault, open_vault
from .wishlist import load_wishes, wish_ui, wishlist_page
from .options import players_range
from .sheet import load_sheet, render_sheet, sheets_of

MARKER = ".tabula-site"          # marks a folder made by `tabula site`, so it can be safely replaced

SITE_UI = {
    "en": {"games": "games", "players": "Players", "any": "any", "duration": "Duration", "up_to": "up to {} min",
           "search": "Search a game, a designer…", "count": "{} of {} games", "none": "No game matches.",
           "rules": "Rules", "key": "Key rules", "turn": "Turn summary", "all_games": "All games", "min": "min", "players_n": "{} players",
           "age": "{}+", "reset": "Reset", "tags": "Tags", "sheet": "Score sheet"},
    "fr": {"games": "jeux", "players": "Joueurs", "any": "tous", "duration": "Durée", "up_to": "jusqu'à {} min",
           "search": "Chercher un jeu, un auteur…", "count": "{} jeux sur {}", "none": "Aucun jeu ne correspond.",
           "rules": "Règles", "key": "Règles clés", "turn": "Résumé du tour", "all_games": "Tous les jeux", "min": "min",
           "players_n": "{} joueurs", "age": "{} ans et +", "reset": "Réinitialiser", "tags": "Étiquettes", "sheet": "Feuille de score"},
    "de": {"games": "Spiele", "players": "Spieler", "any": "alle", "duration": "Dauer", "up_to": "bis {} Min.",
           "search": "Spiel oder Autor suchen…", "count": "{} von {} Spielen", "none": "Kein Spiel passt.",
           "rules": "Regeln", "key": "Kernregeln", "turn": "Spielzug", "all_games": "Alle Spiele", "min": "Min.",
           "players_n": "{} Spieler", "age": "ab {}", "reset": "Zurücksetzen", "tags": "Schlagwörter", "sheet": "Wertungsblatt"},
}
DURATIONS = [15, 30, 45, 60, 90, 120, 180]


def page_name(kind: str, lang: str, default: str) -> str:
    """index.html / index.fr.html (rules) and key.html / key.fr.html (cheat sheet)."""
    return f"{kind}.html" if lang == default else f"{kind}.{lang}.html"


def as_list(v) -> list[str]:
    if v is None:
        return []
    return [str(x) for x in v] if isinstance(v, list) else [str(v)]


def duration_bounds(v) -> tuple[int, int] | None:
    nums = [int(n) for n in re.findall(r"\d+", str(v or ""))]
    return (nums[0], nums[-1]) if nums else None


def prepare(out: Path) -> None:
    """Create the output folder, or empty it if `tabula site` made it. Refuse to touch any other folder."""
    if out.exists() and not out.is_dir():
        raise SystemExit(f"tabula: {out} is a file, not a folder")
    if out.exists() and any(out.iterdir()):
        if not (out / MARKER).exists():
            raise SystemExit(f"tabula: {out} is not empty and wasn't made by 'tabula site'; "
                             f"choose another folder with -o, or empty it first")
        for child in out.iterdir():
            shutil.rmtree(child) if child.is_dir() else child.unlink()
    out.mkdir(parents=True, exist_ok=True)
    (out / MARKER).write_text("made by tabula site; this folder is replaced on every run\n", encoding="utf-8")


def ui_for(lang: str) -> dict:
    return SITE_UI.get(lang, SITE_UI.get(lang.split("-")[0], SITE_UI["en"]))


def game_nav(base: Game, lang: str, kind: str, has_key: dict[str, bool], sheets=(), has_turn=None,
             wished: int = 0) -> str:
    """Links above a game page, in the page's language: all games · rules / key rules · languages."""
    esc = html.escape
    ui = ui_for(lang)
    d = base.default_language
    parts = [f'<a href="../index.html">← {esc(ui["all_games"])}</a>']
    for k, label in (("index", ui["rules"]), ("key", ui["key"]), ("turn", ui["turn"])):
        if (k == "key" and not has_key.get(lang)) or (k == "turn" and not (has_turn or {}).get(lang)):
            continue
        parts.append(f'<span class="here">{esc(label)}</span>' if k == kind
                     else f'<a href="{page_name(k, lang, d)}">{esc(label)}</a>')
    for href, title in sheets:                   # score sheets: pages to print
        label = ui["sheet"] if len(sheets) == 1 else title
        parts.append(f'<a href="{href}" title="{esc(title)}">{esc(label)} ⎙</a>')
    if wished:                                  # extensions of this game on the wishlist
        parts.append(f'<a href="../wishlist.html#for-{esc(base.slug)}">♡ {esc(wish_ui(lang)["wanted"])} ({wished})</a>')
    if len(base.languages) > 1:
        langs = []
        for l in base.languages:
            have = {"index": True, "key": has_key.get(l), "turn": (has_turn or {}).get(l)}
            target = kind if have.get(kind) else "index"
            langs.append(f'<span class="here">{l.upper()}</span>' if l == lang
                         else f'<a href="{page_name(target, l, d)}" hreflang="{l}">{l.upper()}</a>')
        parts.append(" · ".join(langs))
    return "".join(parts)


def write_game(vault: Vault, path: Path, out: Path, wished: dict | None = None) -> dict:
    """Write every page of one game; return what the index needs to know about it."""
    base = vault.load(path)
    folder = out / base.slug
    folder.mkdir()
    ctx = Ctx(None, set(), True)                 # everything, with badges: a reference page
    versions = {lang: (base if lang == base.default_language else vault.load(path, lang)) for lang in base.languages}
    filtered = {lang: filter_blocks(g.blocks, ctx) for lang, g in versions.items()}
    keys = {lang: select_key(blocks) for lang, blocks in filtered.items()}
    has_key = {lang: bool(k) for lang, k in keys.items()}
    turns = {lang: select_turn(blocks) for lang, blocks in filtered.items()}
    has_turn = {lang: bool(t) for lang, t in turns.items()}
    sheets = []
    for s in sheets_of(path, vault.root):
        sh = load_sheet(s, vault)
        name = f"sheet-{s.stem}.html"
        (folder / name).write_text(render_sheet(sh), encoding="utf-8")
        sheets.append((name, sh.title))
    for lang, g in versions.items():
        r = HtmlRenderer(g, filtered[lang], ctx, interactive=True)
        r.game_href = "../{}/index.html"
        nav = game_nav(base, lang, "index", has_key, sheets, has_turn, (wished or {}).get(base.slug, 0))
        (folder / page_name("index", lang, base.default_language)).write_text(r.page(nav=nav), encoding="utf-8")
        if keys[lang]:
            r = HtmlRenderer(g, keys[lang], ctx, key_only=True, interactive=True)
            r.game_href = "../{}/index.html"
            nav = game_nav(base, lang, "key", has_key, sheets, has_turn, (wished or {}).get(base.slug, 0))
            (folder / page_name("key", lang, base.default_language)).write_text(
                r.page(f" — {r.t['key']}", nav=nav), encoding="utf-8")
        if turns[lang]:
            r = HtmlRenderer(g, turns[lang], ctx, interactive=True)
            r.game_href = "../{}/index.html"
            r.sel_label, r.paper = r.t["turn"], "a5"
            nav = game_nav(base, lang, "turn", has_key, sheets, has_turn, (wished or {}).get(base.slug, 0))
            (folder / page_name("turn", lang, base.default_language)).write_text(
                r.page(f" — {r.t['turn']}", nav=nav), encoding="utf-8")
    cover = ""
    if base.cover and base.cover.is_file():
        src = base.cover
        shutil.copyfile(src, folder / f"cover{src.suffix.lower()}")
        cover = f"{base.slug}/cover{src.suffix.lower()}"
    shown = versions.get(vault.language, base)       # the title in the vault's language, when there is one
    return {"game": base, "shown": shown, "has_key": has_key, "has_turn": has_turn, "sheets": len(sheets), "cover": cover,
            "errors": sum(i.level == "error" for i in base.issues)}


def index_page(vault: Vault, entries: list[dict], ui: dict, lang: str, wishes: int = 0) -> str:
    esc = html.escape
    name = str(vault.config.get("name") or vault.root.name)
    finite = [hi for e in entries for _, hi in (players_range(e["game"], everything=True) or []) if hi != math.inf]
    los = [lo for e in entries for lo, _ in (players_range(e["game"], everything=True) or [])]
    cap = max([*finite, *los, 6])
    tags = sorted({t for e in entries for t in as_list(e["game"].meta.get("type")) + as_list(e["game"].meta.get("tags"))},
                  key=fold)
    cards = []
    for e in sorted(entries, key=lambda e: fold(e["shown"].title)):
        g, shown = e["game"], e["shown"]
        meta = g.meta
        rng = players_range(g, everything=True)          # with an extension counts too
        counts = " ".join(str(n) for n in range(1, cap + 1) if in_range(rng, n)) if rng else "*"
        dur = duration_bounds(meta.get("duration"))
        game_tags = as_list(meta.get("type")) + as_list(meta.get("tags"))
        people = as_list(meta.get("designer"))
        text = fold(" ".join([shown.title, g.title, g.slug, *people, *game_tags, str(meta.get("location") or "")]))
        facts = []
        if meta.get("players") is not None:
            facts.append(ui["players_n"].format(str(meta["players"]).replace("-", "–")))
        if dur:
            facts.append(f'{str(meta["duration"]).replace("-", "–")} {ui["min"]}')
        if meta.get("age") is not None:
            facts.append(ui["age"].format(str(meta["age"]).rstrip("+")))
        d = g.default_language
        # the rules in the vault's language when the game has it, else in the game's own language
        main_lang = lang if lang in g.languages else d
        links = [f'<a href="{g.slug}/{page_name("index", main_lang, d)}">{esc(ui["rules"])}</a>']
        if e["has_key"].get(main_lang):
            links.append(f'<a href="{g.slug}/{page_name("key", main_lang, d)}">{esc(ui["key"])}</a>')
        others = [l for l in g.languages if l != main_lang]
        if others:
            links.append(" · ".join(f'<a href="{g.slug}/{page_name("index", l, d)}" hreflang="{l}">{l.upper()}</a>'
                                    for l in others))
        cover = (f'<img src="{esc(e["cover"])}" alt="" loading="lazy">' if e["cover"]
                 else f'<span class="initial" aria-hidden="true">{esc(shown.title[:1].upper())}</span>')
        cards.append(f"""<li class="game-card" data-players="{counts}" data-dmax="{dur[1] if dur else 0}"
  data-tags="{esc('|'.join(game_tags))}" data-text="{esc(text)}">
  <a class="cover" href="{g.slug}/{page_name('index', main_lang, d)}" tabindex="-1">{cover}</a>
  <div class="body">
    <h2><a href="{g.slug}/{page_name('index', main_lang, d)}">{esc(shown.title)}</a></h2>
    {f'<p class="facts">{esc(" · ".join(facts))}</p>' if facts else ""}
    {f'<p class="people">{esc(", ".join(people))}</p>' if people else ""}
    {f'<p class="tags">{"".join(f"<span>{esc(t)}</span>" for t in game_tags)}</p>' if game_tags else ""}
    {f'<p class="location">{esc(str(meta["location"]))}</p>' if meta.get("location") else ""}
    <p class="links">{" ".join(links)}</p>
  </div>
</li>""")
    player_opts = "".join(f'<option value="{n}">{n}</option>' for n in range(1, cap + 1))
    dur_opts = "".join(f'<option value="{m}">{esc(ui["up_to"].format(m))}</option>' for m in DURATIONS)
    tag_buttons = "".join(f'<button type="button" class="tag" aria-pressed="false" data-tag="{esc(t)}">{esc(t)}</button>'
                          for t in tags)
    strings = json.dumps({"count": ui["count"]}, ensure_ascii=False)
    fonts = ('<link rel="preconnect" href="https://fonts.googleapis.com">'
             '<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Atkinson+Hyperlegible:wght@400;700'
             '&family=Literata:opsz,wght@7..72,400;7..72,600;7..72,700&display=swap">')
    return f"""<!doctype html>
<html lang="{esc(lang)}">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{esc(name)}</title>
{fonts}
<style>{HTML_CSS}{INDEX_CSS}</style>
</head>
<body>
<div class="vault">
<header class="vault-head">
  <h1>{esc(name)}</h1>
  {f'<a class="wishlist-link" href="wishlist.html">♡ {esc(wish_ui(lang)["link"].format(wishes))}</a>' if wishes else ""}
  <p class="count" id="count">{esc(ui["count"].format(len(entries), len(entries)))}</p>
</header>
<form class="filters" id="filters" role="search" onsubmit="return false">
  <input type="search" id="q" placeholder="{esc(ui["search"])}" aria-label="{esc(ui["search"])}">
  <label>{esc(ui["players"])} <select id="players"><option value="">{esc(ui["any"])}</option>{player_opts}</select></label>
  <label>{esc(ui["duration"])} <select id="duration"><option value="">{esc(ui["any"])}</option>{dur_opts}</select></label>
  <button type="reset" id="reset">{esc(ui["reset"])}</button>
  {f'<div class="tag-list" role="group" aria-label="{esc(ui["tags"])}">{tag_buttons}</div>' if tags else ""}
</form>
<ul class="games" id="games">
{"".join(cards)}
</ul>
<p class="empty" id="empty" hidden>{esc(ui["none"])}</p>
</div>
<script>{INDEX_JS.replace("__STRINGS__", strings)}</script>
</body>
</html>
"""


INDEX_CSS = r"""
body{min-height:100vh}
.vault{max-width:72rem;margin:0 auto;padding:3rem 2rem 5rem}
.vault-head{display:flex;flex-wrap:wrap;align-items:baseline;justify-content:space-between;gap:.5rem 2rem;
  border-bottom:2px solid var(--ink);padding-bottom:1.2rem}
.vault-head h1{font:600 clamp(2.2rem,5vw,3.2rem)/1.05 var(--serif);margin:0;letter-spacing:-.015em}
.vault-head .count{margin:0;color:var(--muted);font:.95rem var(--sans)}
.vault-head .wishlist-link{font:.95rem var(--sans);color:var(--term);text-decoration:none;margin-left:auto}
.filters{display:flex;flex-wrap:wrap;gap:.7rem 1.2rem;align-items:center;margin:1.4rem 0 1.8rem;font:.95rem var(--sans)}
.filters input[type=search]{flex:1 1 16rem;min-width:0;font:inherit;padding:.55rem .8rem;border:1px solid var(--rule);
  border-radius:8px;background:var(--card);color:var(--ink)}
.filters label{display:flex;align-items:center;gap:.45rem;color:var(--muted)}
.filters select,.filters button{font:inherit;padding:.45rem .6rem;border:1px solid var(--rule);border-radius:8px;
  background:var(--card);color:var(--ink)}
.filters button{cursor:pointer}
.tag-list{flex-basis:100%;display:flex;flex-wrap:wrap;gap:.4rem}
.tag-list .tag{border-radius:999px;padding:.3rem .75rem;font-size:.85rem}
.tag-list .tag[aria-pressed=true]{background:var(--ink);color:var(--paper);border-color:var(--ink)}
.games{list-style:none;margin:0;padding:0;display:grid;grid-template-columns:repeat(auto-fill,minmax(19rem,1fr));gap:1rem}
.game-card{display:grid;grid-template-columns:5.5rem 1fr;gap:1rem;padding:1rem;background:var(--card);
  border:1px solid var(--rule);border-radius:10px}
.game-card[hidden]{display:none}
.game-card .cover{display:block;text-decoration:none;width:5.5rem;height:5.5rem;border-radius:6px;overflow:hidden;background:var(--desk)}
.game-card .cover img{width:100%;height:100%;object-fit:cover;display:block}
.game-card .initial{display:flex;width:100%;height:100%;align-items:center;justify-content:center;
  font:600 2.2rem var(--serif);color:var(--muted)}
.game-card h2{font:600 1.25rem/1.2 var(--serif);margin:0 0 .3rem}
.game-card h2 a{color:var(--ink);text-decoration:none}
.game-card h2 a:hover{color:var(--term)}
.game-card p{margin:.2rem 0;font:.88rem/1.45 var(--sans)}
.game-card .facts{color:var(--ink)}
.game-card .people,.game-card .location{color:var(--muted)}
.game-card .tags span{display:inline-block;margin:0 .3rem .25rem 0;padding:.05rem .5rem;border:1px solid var(--rule);
  border-radius:999px;font-size:.78rem;color:var(--muted)}
.game-card .links{margin-top:.5rem}
.game-card .links a{color:var(--term);margin-right:.8rem;text-decoration:none;font-weight:600}
.game-card .links a:hover{text-decoration:underline}
.empty{color:var(--muted);font:1rem var(--sans);text-align:center;padding:3rem 0}
@media (max-width:40rem){.vault{padding:2rem 1rem 4rem}.game-card{grid-template-columns:4rem 1fr}
  .game-card .cover{width:4rem;height:4rem}}
"""

INDEX_JS = r"""
(function () {
  var S = __STRINGS__;
  var cards = Array.prototype.slice.call(document.querySelectorAll('.game-card'));
  var q = document.getElementById('q'), players = document.getElementById('players'),
      duration = document.getElementById('duration'), count = document.getElementById('count'),
      empty = document.getElementById('empty');
  var tagButtons = Array.prototype.slice.call(document.querySelectorAll('.tag'));
  function fold(s) { return s.normalize('NFD').replace(/[̀-ͯ]/g, '').toLowerCase(); }
  function apply() {
    var p = players.value, d = parseInt(duration.value, 10) || 0, text = fold(q.value.trim());
    var tags = tagButtons.filter(function (b) { return b.getAttribute('aria-pressed') === 'true'; })
                         .map(function (b) { return b.dataset.tag; });
    var shown = 0;
    cards.forEach(function (c) {
      var ok = true;
      if (p && c.dataset.players !== '*' && c.dataset.players.split(' ').indexOf(p) < 0) ok = false;
      if (d && parseInt(c.dataset.dmax, 10) > d) ok = false;
      var own = c.dataset.tags ? c.dataset.tags.split('|') : [];
      if (tags.some(function (t) { return own.indexOf(t) < 0; })) ok = false;
      if (text && text.split(/\s+/).some(function (w) { return c.dataset.text.indexOf(w) < 0; })) ok = false;
      c.hidden = !ok;
      if (ok) shown++;
    });
    count.textContent = S.count.replace('{}', shown).replace('{}', cards.length);
    empty.hidden = shown > 0;
  }
  q.addEventListener('input', apply);
  players.addEventListener('change', apply);
  duration.addEventListener('change', apply);
  tagButtons.forEach(function (b) {
    b.addEventListener('click', function () {
      b.setAttribute('aria-pressed', b.getAttribute('aria-pressed') === 'true' ? 'false' : 'true');
      apply();
    });
  });
  document.getElementById('filters').addEventListener('reset', function () {
    tagButtons.forEach(function (b) { b.setAttribute('aria-pressed', 'false'); });
    setTimeout(apply, 0);
  });
})();
"""


def cmd_site(args) -> int:
    vault = open_vault(args.vault)
    out = Path(args.output or "site").resolve()
    if out == vault.root:
        raise SystemExit("tabula: the site folder can't be the vault itself; choose another with -o")
    paths = vault.discover()
    if not paths:
        print(f"tabula: no games in {vault.root}", file=sys.stderr)
        return 1
    prepare(out)
    lang = vault.language
    ui = ui_for(lang)
    wishes, _ = load_wishes(vault)
    wished = {}                                       # game slug -> how many of its extensions are wished for
    for w in wishes:
        if w.get("for"):
            wished[str(w["for"])] = wished.get(str(w["for"]), 0) + 1
    entries = [write_game(vault, p, out, wished) for p in paths]
    (out / "index.html").write_text(index_page(vault, entries, ui, lang, len(wishes)), encoding="utf-8")
    if wishes:
        (out / "wishlist.html").write_text(wishlist_page(vault, wishes, lang, HTML_CSS + INDEX_CSS), encoding="utf-8")
    pages = sum(len(e["game"].languages) + sum(e["has_key"].values()) + sum(e["has_turn"].values()) + e["sheets"]
                for e in entries)
    pages += 1 if wishes else 0
    print(f"wrote {out} ({len(entries)} games, {pages + 1} pages) — open {out / 'index.html'}")
    broken = [e["game"].slug for e in entries if e["errors"]]
    if broken:
        print(f"tabula: {', '.join(broken)} {'has' if len(broken) == 1 else 'have'} errors; "
              f"run 'tabula check'", file=sys.stderr)
    return 0
