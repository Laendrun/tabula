"""The wishlist: games and extensions you'd like, in wishlist.yaml at the vault's root.

    - name: Cascadia
      priority: 1                  # 1 = most wanted
      price: 35 CHF
      link: https://…
    - name: Pandora's Box
      for: frantic                 # an extension of a game in the vault (its slug or its title)
      priority: 2
      note: the purple one
    - name: "Frantic: all the extensions"
      for: frantic
    - name: Troublemaker
      for: frantic
      in: "Frantic: all the extensions"     # also in that pack: either the pack, or the single ones

`tabula wish` lists it, `tabula wish add "Name" --for frantic --priority 1` and `tabula wish remove "Name"`
change it, `tabula check` checks it and `tabula site` writes a wishlist page.
"""
from __future__ import annotations

import difflib
import html
import json
import os
import sys
from pathlib import Path

import yaml

from .source import Issues
from .syntax import fold

WISHLIST = "wishlist.yaml"
WISH_KEYS = ("name", "for", "in", "priority", "price", "link", "note")


def wishlist_path(vault) -> Path:
    return vault.root / WISHLIST


def load_wishes(vault) -> tuple[list[dict], Issues]:
    """The wishes, each with its 'line' (1-based), and the problems found reading the file."""
    iss = Issues()
    path = wishlist_path(vault)
    if not path.is_file():
        return [], iss
    text = path.read_text(encoding="utf-8")
    try:
        node = yaml.compose(text)
        data = yaml.safe_load(text)
    except yaml.YAMLError as e:
        mark = getattr(e, "problem_mark", None)
        problem = str(getattr(e, "problem", e))
        hint = (" (a value containing ': ' needs quotes, like name: \"Pandora: the box\")"
                if "mapping values are not allowed" in problem else "")
        iss.error(path, (mark.line + 1) if mark else 1, f"invalid YAML: {problem}{hint}")
        return [], iss
    if data is None:
        return [], iss
    if not isinstance(data, list):
        iss.error(path, 1, "the wishlist is a list: one '- name: …' entry per game or extension")
        return [], iss
    out = []
    for item, n in zip(data, node.value):
        line = n.start_mark.line + 1
        if not isinstance(item, dict):
            item = {"name": str(item)}                 # "- Cascadia": just a name
        out.append({**{str(k): v for k, v in item.items()}, "line": line})
    games = {p.stem: vault.load(p).title for p in vault.discover()} if any(w.get("for") for w in out) else {}
    for w in out:
        w["game"] = resolve_game(w.get("for"), games)
    return out, iss


def resolve_game(value, games: dict[str, str]) -> str | None:
    """The slug of the game a wish is for: written as its slug or its title (case and accents ignored)."""
    if value is None:
        return None
    v = str(value)
    if v in games:
        return v
    return next((s for s, title in games.items() if fold(title) == fold(v) or fold(s) == fold(v)), None)


def pack_names(w: dict) -> list[str]:
    v = w.get("in")
    return [str(x) for x in v] if isinstance(v, list) else [str(v)] if v else []


def wish_tree(wishes: list[dict]) -> list[tuple[dict, list[dict]]]:
    """(wish, the wishes it contains) for the wishes that aren't in a pack on the list, sorted by priority
    (a pack takes the best priority of its parts)."""
    by_name = {fold(str(w.get("name", ""))): w for w in wishes}
    parts: dict[int, list[dict]] = {}
    inside = set()
    for w in wishes:
        for pack in pack_names(w):
            if (p := by_name.get(fold(pack))) is not None and p is not w:
                parts.setdefault(id(p), []).append(w)
                inside.add(id(w))
    tops = [w for w in wishes if id(w) not in inside]

    def prio(w):
        ps = [x.get("priority") for x in [w, *parts.get(id(w), [])] if isinstance(x.get("priority"), int)]
        return min(ps) if ps else 99
    tops.sort(key=lambda w: (prio(w), fold(str(w.get("name", "")))))
    return [(w, sorted_wishes(parts.get(id(w), []))) for w in tops]


def check_wishes(vault) -> Issues:
    wishes, iss = load_wishes(vault)
    path = wishlist_path(vault)
    titles = game_titles(vault) if any(w.get("for") for w in wishes) else {}
    slugs = list(titles)
    names = [str(w.get("name", "")) for w in wishes]
    for w in wishes:
        ln = w["line"]
        if not str(w.get("name") or "").strip():
            iss.error(path, ln, "a wish needs a 'name'")
        for k in w:
            if k not in WISH_KEYS and k not in ("line", "game"):          # line, game: worked out here
                close = difflib.get_close_matches(k, WISH_KEYS, n=1, cutoff=0.6)
                iss.warn(path, ln, f"unknown key '{k}'" + (f" (did you mean '{close[0]}'?)" if close
                                                        else f" (use {', '.join(WISH_KEYS)})"))
        game = w.get("for")
        if game is not None and w.get("game") is None:
            close = difflib.get_close_matches(str(game), slugs + list(titles.values()), n=1, cutoff=0.6)
            iss.error(path, ln, f"'for: {game}' is not a game in the vault" +
                      (f" (did you mean '{close[0]}'?)" if close else
                       f" (write the game's slug or title, like {slugs[0]})" if slugs else ""))
        for pack in pack_names(w):
            if fold(pack) == fold(str(w.get("name", ""))):
                iss.error(path, ln, f"'{w.get('name')}' can't be in itself")
            elif not any(fold(pack) == fold(n) for n in names):
                close = difflib.get_close_matches(pack, names, n=1, cutoff=0.6)
                iss.warn(path, ln, f"'in: {pack}' is not on the wishlist" +
                         (f" (did you mean '{close[0]}'?)" if close else " (add the pack as a wish too)"))
        pr = w.get("priority")
        if pr is not None and (not isinstance(pr, int) or isinstance(pr, bool) or pr < 1):
            iss.error(path, ln, f"priority must be a whole number, 1 for the most wanted (got '{pr}')")
        link = w.get("link")
        if link and not str(link).startswith(("http://", "https://")):
            iss.warn(path, ln, f"link should be a web address starting with https:// (got '{link}')")
    return iss


def sorted_wishes(wishes: list[dict]) -> list[dict]:
    return sorted(wishes, key=lambda w: (w.get("priority") if isinstance(w.get("priority"), int) else 99,
                                         fold(str(w.get("name", "")))))


def game_titles(vault) -> dict[str, str]:
    return {p.stem: vault.load(p).title for p in vault.discover()}


# ------------------------------------------------------------------ command

def yaml_scalar(v) -> str:
    """As written when YAML reads it back the same (35 CHF, https://…), else quoted."""
    if isinstance(v, int):
        return str(v)
    s = str(v)
    try:
        if "#" not in s and s == s.strip() and yaml.safe_load(f"k: {s}") == {"k": s}:
            return s
    except yaml.YAMLError:
        pass
    return json.dumps(s, ensure_ascii=False)               # a JSON string is valid YAML


def add_wish(vault, entry: dict) -> None:
    path = wishlist_path(vault)
    text = path.read_text(encoding="utf-8") if path.is_file() else \
        "# Games and extensions we'd like (tabula wish). 'for:' links an extension to a game of the vault.\n"
    if text and not text.endswith("\n"):
        text += "\n"
    lines = [f"- name: {yaml_scalar(entry['name'])}"]
    lines += [f"  {k}: {yaml_scalar(entry[k])}" for k in WISH_KEYS[1:] if entry.get(k) not in (None, "")]
    path.write_text(text + "\n".join(lines) + "\n", encoding="utf-8")


def remove_wish(vault, wish: dict, wishes: list[dict]) -> None:
    """Delete a wish's lines from the file, keeping everything else (comments included) as written."""
    path = wishlist_path(vault)
    lines = path.read_text(encoding="utf-8").split("\n")
    starts = sorted(w["line"] for w in wishes)
    start = wish["line"]
    after = [s for s in starts if s > start]
    end = after[0] - 1 if after else len(lines)
    while end > start and (not lines[end - 1].strip() or lines[end - 1].lstrip().startswith("#")):
        end -= 1                                # blank lines and comments before the next wish are its own
    del lines[start - 1:end]
    path.write_text("\n".join(lines), encoding="utf-8")


def cmd_wish(args) -> int:
    from .terminal import Style
    from .vault import open_vault
    vault = open_vault(args.vault)
    wishes, iss = load_wishes(vault)
    if iss:
        for i in iss:
            print(f"tabula: {WISHLIST}:{i.line}: {i.msg}", file=sys.stderr)
        return 2
    if args.action == "add":
        if not args.name:
            raise SystemExit('tabula: tabula wish add "Name" [--for GAME] [--priority N] [--price …] [--link …]')
        game = None
        if args.for_game:
            game = vault.find(args.for_game).stem
        entry = {"name": args.name, "for": game, "in": args.in_pack, "priority": args.priority,
                 "price": args.price, "link": args.link, "note": args.note}
        if any(fold(str(w.get("name", ""))) == fold(args.name) and w.get("game") == game for w in wishes):
            raise SystemExit(f"tabula: '{args.name}' is already on the wishlist")
        add_wish(vault, entry)
        print(f"added '{args.name}'" + (f" (for {game})" if game else "") + f" to {wishlist_path(vault)}")
        return 0
    if args.action == "remove":
        if not args.name:
            raise SystemExit('tabula: tabula wish remove "Name"')
        slug = vault.find(args.for_game).stem if args.for_game else None
        hits = [w for w in wishes if fold(str(w.get("name", ""))) == fold(args.name)
                and (not slug or w.get("game") == slug)]
        if not hits:
            names = [str(w.get("name", "")) for w in wishes]
            close = difflib.get_close_matches(args.name, names, n=1, cutoff=0.5)
            raise SystemExit(f"tabula: no wish '{args.name}'" + (f" (did you mean '{close[0]}'?)" if close else ""))
        if len(hits) > 1:
            raise SystemExit(f"tabula: several wishes are called '{args.name}'; add --for GAME")
        parts = dict((id(w), p) for w, p in wish_tree(wishes)).get(id(hits[0]), [])   # a pack: its parts too
        for w in sorted([hits[0], *parts], key=lambda w: -w["line"]):                 # from the end: lines stay
            remove_wish(vault, w, wishes)
        print(f"removed '{hits[0]['name']}'" + (f" and what it contains ({', '.join(str(p['name']) for p in parts)})"
                                               if parts else "") + f" from {wishlist_path(vault)}")
        return 0
    # list
    if args.for_game:
        slug = vault.find(args.for_game).stem
        wishes = [w for w in wishes if w.get("game") == slug]
    if args.json:
        print(json.dumps([{k: v for k, v in w.items() if k != "line" and (k != "game" or v)} for w in sorted_wishes(wishes)],
                         indent=2, ensure_ascii=False))
        return 0
    if not wishes:
        print(f"the wishlist is empty (add one: tabula wish add \"Name\")")
        return 0
    st = Style(sys.stdout.isatty() and not os.environ.get("NO_COLOR") and not args.no_color)
    titles = game_titles(vault)
    tree = wish_tree(wishes)
    groups = [("Games", [(w, p) for w, p in tree if not w.get("for")]),
              ("Extensions", [(w, p) for w, p in tree if w.get("for")])]
    out = []

    def line(w, pad=""):
        pr = w.get("priority")
        head = pad + (st.yellow(f"{pr}") + " " if isinstance(pr, int) else "  ") + st.bold(str(w.get("name")))
        if w.get("for") and not pad:
            head += st.dim(f"  for {titles.get(w.get('game'), w['for'])}")
        if w.get("price"):
            head += f"  {w['price']}"
        out.append(head)
        for k in ("note", "link"):
            if w.get(k):
                out.append(pad + "    " + (st.dim(str(w[k])) if k == "link" else str(w[k])))
    for label, items in groups:
        if not items:
            continue
        out.append(st.bold(label.upper()))
        for w, parts in items:
            line(w)
            if parts:
                out.append(st.dim("    or separately:"))
                for p in parts:
                    line(p, "    ")
        out.append("")
    print("\n".join(out).rstrip())
    return 0


# ------------------------------------------------------------------ site

WISH_UI = {
    "en": {"title": "Wishlist", "games": "Games", "extensions": "Extensions", "for": "for", "priority": "priority",
           "shop": "Shop", "back": "All games", "link": "Wishlist ({})", "wanted": "Wished for", "or": "or separately:"},
    "fr": {"title": "Liste de souhaits", "games": "Jeux", "extensions": "Extensions", "for": "pour",
           "priority": "priorité", "shop": "Boutique", "back": "Tous les jeux", "link": "Souhaits ({})",
           "wanted": "Souhaité", "or": "ou séparément :"},
    "de": {"title": "Wunschliste", "games": "Spiele", "extensions": "Erweiterungen", "for": "für",
           "priority": "Priorität", "shop": "Shop", "back": "Alle Spiele", "link": "Wunschliste ({})",
           "wanted": "Gewünscht", "or": "oder einzeln:"},
}


def wish_ui(lang: str) -> dict:
    return WISH_UI.get(lang, WISH_UI.get(lang.split("-")[0], WISH_UI["en"]))


def wishlist_page(vault, wishes: list[dict], lang: str, css: str) -> str:
    esc = html.escape
    ui = wish_ui(lang)
    titles = game_titles(vault)
    name = str(vault.config.get("name") or vault.root.name)

    def item(w, parts=()):
        pr = w.get("priority")
        bits = []
        if isinstance(pr, int):
            bits.append(f'<span class="prio" title="{esc(ui["priority"])} {pr}">{pr}</span>')
        bits.append(f'<span class="wname">{esc(str(w.get("name")))}</span>')
        if w.get("for") and not w.get("_part"):
            slug = w.get("game")
            game = (f'<a href="{esc(slug)}/index.html">{esc(titles[slug])}</a>' if slug in titles
                    else esc(str(w["for"])))             # an unknown game (tabula check reports it): no link
            bits.append(f'<span class="wfor">{esc(ui["for"])} {game}</span>')
        if w.get("price"):
            bits.append(f'<span class="price">{esc(str(w["price"]))}</span>')
        if w.get("link"):
            bits.append(f'<a class="shop" href="{esc(str(w["link"]))}" rel="noopener">{esc(ui["shop"])} →</a>')
        note = f'<p class="note">{esc(str(w["note"]))}</p>' if w.get("note") else ""
        anchor = f' id="for-{esc(str(w["game"]))}"' if w.get("game") and not w.get("_part") else ""
        inner = ""
        if parts:
            inner = (f'<p class="or">{esc(ui["or"])}</p><ul class="parts">'
                     + "".join(item({**p, "_part": True}) for p in parts) + "</ul>")
        return f"<li{anchor}><div class=\"wish\">{''.join(bits)}</div>{note}{inner}</li>"

    sections = []
    tree = wish_tree(wishes)
    for key, items in (("games", [(w, p) for w, p in tree if not w.get("for")]),
                       ("extensions", [(w, p) for w, p in tree if w.get("for")])):
        if items:
            sections.append(f'<h2>{esc(ui[key])}</h2><ul class="wishes">'
                            + "".join(item(w, p) for w, p in items) + "</ul>")
    return f"""<!doctype html>
<html lang="{esc(lang)}">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{esc(ui["title"])} — {esc(name)}</title>
<style>{css}{WISH_CSS}</style>
</head>
<body>
<div class="vault">
<nav class="site"><a href="index.html">← {esc(ui["back"])}</a></nav>
<header class="vault-head"><h1>{esc(ui["title"])}</h1></header>
{"".join(sections)}
</div>
</body>
</html>
"""


WISH_CSS = """
nav.site{font:.92rem var(--sans);margin-bottom:1.2rem}
nav.site a{color:var(--term)}
.vault h2{font:600 1.4rem var(--serif);margin:2rem 0 .6rem}
ul.wishes{list-style:none;padding:0;margin:0}
ul.wishes li{border-bottom:1px solid var(--rule);padding:.7rem 0}
.wish{display:flex;flex-wrap:wrap;align-items:baseline;gap:.4rem .9rem;font:1rem var(--sans)}
.wname{font-weight:700;font-size:1.08rem}
.prio{display:inline-grid;place-items:center;min-width:1.6rem;height:1.6rem;border-radius:999px;
  background:var(--open-bg);color:var(--open);font-weight:700;font-size:.85rem}
.wfor{color:var(--muted)}
.wfor a{color:var(--term)}
.price{font-variant-numeric:tabular-nums}
.shop{margin-left:auto;color:var(--term);font-weight:600}
ul.wishes .note{margin:.25rem 0 0;color:var(--muted);font-size:.95rem}
ul.wishes .or{margin:.45rem 0 .1rem 2.4rem;color:var(--muted);font:.88rem var(--sans);font-style:italic}
ul.wishes ul.parts{list-style:none;margin:0 0 0 2.4rem;padding:0;border-left:2px solid var(--rule)}
ul.wishes ul.parts li{border:0;padding:.3rem 0 .3rem .8rem}
ul.wishes ul.parts .wname{font-size:1rem;font-weight:600}
a.wishlist-link{font:.95rem var(--sans);color:var(--term)}
"""
