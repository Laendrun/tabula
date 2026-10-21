"""Score sheets (.sheet): printable grids to fill in during a game.

A .sheet file sits next to its game (frantic/frantic.sheet, frantic/manches.sheet; frantic.sheet for a
standalone game). It has a frontmatter (title, size, orientation…) and Markdown: headings, text and mostly
tables, where an empty cell is a box to fill in.

    | Blason     | Joueur 1 | <  | Joueur 2 |     <  merges with the cell on the left
    |------------|----------|----|----------|     ^  merges with the cell above
    | Noble :or: |          |    |          |     // a shaded cell, not to fill in
    | Total      | //       |    |          |

`tabula sheet GAME` writes each sheet as an HTML page the size of the paper, ready to print (or to save as PDF).
"""
from __future__ import annotations

import base64
import difflib
import html
import mimetypes
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

from .blocks import Block, is_sep_row, parse_blocks
from .source import Issues, UNSAVED, read_source
from .symbols import SYMBOL_RE, expand_symbols, merged_symbols, symbol_problems
from .syntax import IMAGE_RE, REF_RE
from .values import expand_values, merged_values

PAPER = {"a0": (841, 1189), "a1": (594, 841), "a2": (420, 594), "a3": (297, 420), "a4": (210, 297), "a5": (148, 210),
         "a6": (105, 148), "b4": (250, 353), "b5": (176, 250), "letter": (216, 279), "legal": (216, 356),
         "tabloid": (279, 432)}
SHEET_KEYS = ("title", "game", "size", "orientation", "margin", "font_size", "fit", "language", "symbols", "values",
              "rounds")
PLAYER_RE = re.compile(r"\{(n|player)\}")
ROUND_RE = re.compile(r"\{r\}")
DEFAULT_MAX_PLAYERS = 6          # for a game "for 2+ players"
MERGE_LEFT, MERGE_UP, BLOCKED = "<", "^", "//"


@dataclass
class Sheet:
    path: Path
    meta: dict
    blocks: list[Block]
    issues: Issues
    game_meta: dict = field(default_factory=dict)
    lines: list = field(default_factory=list)

    @property
    def title(self) -> str:
        return str(self.meta.get("title") or self.game_meta.get("title") or self.path.stem)

    @property
    def paper(self) -> tuple[float, float]:
        """(width, height) in mm, in the sheet's orientation."""
        size = str(self.meta.get("size") or "a4").lower().replace(" ", "")
        if size in PAPER:
            w, h = PAPER[size]
        elif m := re.fullmatch(r"(\d+(?:\.\d+)?)x(\d+(?:\.\d+)?)(?:mm)?", size):
            w, h = float(m.group(1)), float(m.group(2))
        else:
            w, h = PAPER["a4"]
        landscape = str(self.meta.get("orientation") or "portrait").lower() == "landscape"
        return (max(w, h), min(w, h)) if landscape else (min(w, h), max(w, h))

    @property
    def margin(self) -> float:
        try:
            return float(self.meta.get("margin", 10))
        except (TypeError, ValueError):
            return 10.0


def player_count(sheet: Sheet, wanted: int | None) -> int:
    """How many player columns: -p N (within the game's player count), else the game's most."""
    from .syntax import bounds, in_range, parse_range
    rng = parse_range(sheet.game_meta.get("players"))
    if wanted is not None:
        if wanted < 1:
            raise SystemExit("tabula: -p needs at least 1 player")
        if rng and not in_range(rng, wanted):
            raise SystemExit(f"tabula: {sheet.game_meta.get('title', 'this game')} is for "
                             f"{sheet.game_meta.get('players')} players, not {wanted}")
        return wanted
    if not rng:
        return DEFAULT_MAX_PLAYERS
    hi = bounds(rng)[1]
    return int(hi) if hi < 99 else max(DEFAULT_MAX_PLAYERS, int(bounds(rng)[0]))


def expand_grid(rows: list[list[str]], players: int, rounds: int) -> list[list[str]]:
    """Repeat the {player} columns (with the < columns joined to them) once per player, and the {r} rows once
    per round. rows[0] is the heading row."""
    if not rows:
        return rows
    n = max(len(r) for r in rows)
    rows = [r + [""] * (n - len(r)) for r in rows]
    head = rows[0]
    groups = []                        # (first column, number of columns)
    j = 0
    while j < n:
        if PLAYER_RE.search(head[j]):
            k = j + 1
            while k < n and head[k] == MERGE_LEFT:
                k += 1
            groups.append((j, k - j))
            j = k
        else:
            j += 1
    if groups:
        starts = {g[0]: g[1] for g in groups}
        out = []
        for r, cells in enumerate(rows):
            new, j = [], 0
            while j < n:
                if j in starts:
                    part = cells[j:j + starts[j]]
                    for i in range(1, players + 1):
                        new += [PLAYER_RE.sub(lambda m: str(i) if m.group(1) == "n" else "", c).strip() if r == 0
                                else c.replace("{n}", str(i)) for c in part]
                    j += starts[j]
                else:
                    new.append(cells[j])
                    j += 1
            out.append(new)
        rows = out
    out = []
    for cells in rows:
        if cells and ROUND_RE.search(cells[0]):
            out += [[ROUND_RE.sub(str(i), c) for c in cells] for i in range(1, rounds + 1)]
        else:
            out.append(cells)
    return out


def game_file_for(sheet: Path) -> Path | None:
    """The game a sheet belongs to: the .game of its folder, or the .game with its name (standalone)."""
    folder = sheet.parent
    for cand in (folder / f"{folder.name}.game", sheet.with_suffix(".game")):
        if cand.is_file():
            return cand
    return None


def sheets_of(game_path: Path, vault_root: Path) -> list[Path]:
    """A game's sheets: every .sheet in its folder, or <slug>.sheet next to a standalone game."""
    if game_path.parent.resolve() != vault_root.resolve():
        return sorted(game_path.parent.glob("*.sheet"))
    p = game_path.with_suffix(".sheet")
    return [p] if p.exists() else []


def load_sheet(path: Path, vault) -> Sheet:
    issues = Issues()
    meta, lines = read_source(path, issues)
    game_meta: dict = {}
    if g := game_file_for(path):
        game_meta, _ = read_source(g, Issues())
    base = path.parent
    lines = expand_values(lines, merged_values(vault.config, game_meta, meta), issues, path)
    lines = expand_symbols(lines, merged_symbols(vault.root, base, vault.config, game_meta, meta))
    return Sheet(path, meta, parse_blocks(lines), issues, game_meta, lines)


# ------------------------------------------------------------------ check

def check_sheet(sheet: Sheet, vault) -> Issues:
    iss = Issues()
    iss.extend(sheet.issues)
    p, meta = sheet.path, sheet.meta
    size = str(meta.get("size") or "a4").lower().replace(" ", "")
    if size not in PAPER and not re.fullmatch(r"\d+(?:\.\d+)?x\d+(?:\.\d+)?(?:mm)?", size):
        iss.error(p, 1, f"unknown size '{meta.get('size')}' (a0 to a6, b4, b5, letter, legal, tabloid, or 210x297 in mm)")
    if str(meta.get("orientation") or "portrait").lower() not in ("portrait", "landscape"):
        iss.error(p, 1, f"orientation must be portrait or landscape (got '{meta.get('orientation')}')")
    for key in ("margin", "font_size"):
        if key in meta and not isinstance(meta[key], (int, float)):
            iss.error(p, 1, f"'{key}' must be a number ({'mm' if key == 'margin' else 'points'})")
    for key in meta:
        close = difflib.get_close_matches(str(key), SHEET_KEYS, n=1, cutoff=0.8)
        if str(key) not in SHEET_KEYS and close:
            iss.warn(p, 1, f"'{key}:' in frontmatter: did you mean '{close[0]}'?")
    for msg in symbol_problems(meta.get("symbols"), p.parent):
        iss.error(p, 1, msg)
    names = list(merged_symbols(vault.root, p.parent, vault.config, sheet.game_meta, meta))
    for ln, t in sheet.lines:
        for m in SYMBOL_RE.finditer(re.sub(r"`[^`]*`", "", t)):
            if close := difflib.get_close_matches(m.group(1), names, n=1, cutoff=0.75):
                iss.warn(p, ln, f"':{m.group(1)}:' is not a symbol: did you mean ':{close[0]}:'?")
    for b in sheet.blocks:
        if b.kind != "table":
            continue
        rows = [(ln, cells) for ln, cells in b.rows if not is_sep_row(cells)]
        width = len(rows[0][1]) if rows else 0
        for k, (ln, cells) in enumerate(rows):
            if len(cells) != width:
                iss.warn(p, ln, f"this row has {len(cells)} cells, the first row has {width}")
            if cells and cells[0] == MERGE_LEFT:
                iss.error(p, ln, "'<' in the first column: there is no cell on its left to merge with")
            if k <= 1 and MERGE_UP in cells:
                iss.error(p, ln, "'^' in the first row (or right under the headings): no cell above to merge with")
    return iss


# ------------------------------------------------------------------ render

def esc(s: str) -> str:
    return html.escape(s, quote=True)


def data_uri(base: Path, src: str) -> str:
    if re.match(r"^[a-z]+://", src):
        return src
    f = base / src
    if not f.is_file():
        return src
    mime = mimetypes.guess_type(f.name)[0] or "application/octet-stream"
    return f"data:{mime};base64," + base64.b64encode(f.read_bytes()).decode()


def inline(text: str, base: Path) -> str:
    stash: list[str] = []

    def keep(h: str) -> str:
        stash.append(h)
        return f"\x00{len(stash) - 1}\x00"

    def image(m):
        alt, src = m.group(1), m.group(2)
        cls = ' class="sym"' if alt.startswith("sym:") else ""
        alt = alt[4:] if cls else alt
        return keep(f'<img{cls} src="{esc(data_uri(base, src))}" alt="{esc(alt)}" title="{esc(alt)}">')

    text = re.sub(r"\\([\[\]{}!\\*#|])", lambda m: keep(esc(m.group(1))), text)
    text = IMAGE_RE.sub(image, text)
    text = REF_RE.sub(lambda m: keep(esc((m.group(2) or m.group(1)).lstrip("#").strip())), text)
    text = esc(text)
    text = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", text)
    text = re.sub(r"(?<![*\w])\*(?!\s)(.+?)(?<!\s)\*(?![*\w])", r"<em>\1</em>", text)
    text = re.sub(r"(?<!\w)_(?!\s)(.+?)(?<!\s)_(?!\w)", r"<em>\1</em>", text)
    while "\x00" in text:
        text = re.sub(r"\x00(\d+)\x00", lambda m: stash[int(m.group(1))], text)
    return text


def visible_len(cell: str) -> int:
    return len(re.sub(r"!\[sym:([^\]]*)\]\([^)]*\)", "XX", re.sub(r"\*\*|__|\[\[|\]\]", "", cell)))


def render_table(b: Block, base: Path, players: int = DEFAULT_MAX_PLAYERS, rounds: int = 10) -> tuple[str, int]:
    """The table's HTML, and its number of body rows (to share the page's height)."""
    rows = expand_grid([cells for _, cells in b.rows if not is_sep_row(cells)], players, rounds)
    n = max((len(r) for r in rows), default=0)
    rows = [r + [""] * (n - len(r)) for r in rows]
    head = rows[0] if rows and any(c.strip() for c in rows[0]) else None
    body = rows[1:] if rows else []
    grid = ([head] if head else []) + body
    covered = [[False] * n for _ in grid]
    out = []

    def spans(r, c):
        cs = 1
        while c + cs < n and grid[r][c + cs] == MERGE_LEFT:
            cs += 1
        rs = 1
        while r + rs < len(grid) and grid[r + rs][c] == MERGE_UP:
            rs += 1
        for i in range(r, r + rs):
            for j in range(c, c + cs):
                if (i, j) != (r, c):
                    covered[i][j] = True
        return cs, rs

    # column widths: a first column with row headings gets room for them; the others share the rest equally
    widths = [None] * n
    if n:
        texts = [grid[i][0] for i in range(len(grid)) if grid[i][0] not in (MERGE_LEFT, MERGE_UP, BLOCKED)]
        if any(t.strip() for i, t in enumerate(texts) if not head or i > 0):
            widths[0] = min(max(visible_len(t) for t in texts) + 2, 40)
    cols = "".join(f'<col style="width:{w}ch">' if w else "<col>" for w in widths)
    for r, cells in enumerate(grid):
        tag_row = []
        for c, cell in enumerate(cells):
            if covered[r][c]:
                continue
            if cell in (MERGE_LEFT, MERGE_UP):          # nothing to merge with (check reports it)
                cell = ""
            cs, rs = spans(r, c)
            attrs = (f' colspan="{cs}"' if cs > 1 else "") + (f' rowspan="{rs}"' if rs > 1 else "")
            is_head = (head is not None and r == 0) or (c == 0 and widths[0] is not None and cell.strip())
            tag = "th" if is_head else "td"
            if cell == BLOCKED:
                tag_row.append(f'<td class="x"{attrs}></td>')
            else:
                tag_row.append(f"<{tag}{attrs}>{inline(cell, base)}</{tag}>")
        out.append("<tr>" + "".join(tag_row) + "</tr>")
    thead = f"<thead>{out[0]}</thead>" if head else ""
    tbody = "<tbody>" + "".join(out[1:] if head else out) + "</tbody>"
    return f"<table><colgroup>{cols}</colgroup>{thead}{tbody}</table>", max(len(body), 1)


SHEET_CSS = """
@page { size: %(w)smm %(h)smm; margin: 0 }
* { box-sizing: border-box }
html, body { margin: 0; background: #e6e8eb }
.page { width: %(w)smm; height: %(h)smm; padding: %(m)smm; margin: 8mm auto; background: #fff; color: #111;
        box-shadow: 0 1px 4px rgba(0,0,0,.25); display: flex; flex-direction: column; gap: 3mm; overflow: hidden;
        font: %(f)spt/1.3 "Atkinson Hyperlegible", system-ui, "Segoe UI", Roboto, Helvetica, Arial, sans-serif }
.page > * { flex: none; margin: 0 }
h1 { font-size: 1.7em; line-height: 1.1 } h2 { font-size: 1.3em } h3 { font-size: 1.1em }
p, ul, ol { margin: 0 }
.grid { flex: var(--rows) 1 0; min-height: 0; display: flex }
.grid.natural { flex: none }
table { width: 100%%; border-collapse: collapse; table-layout: fixed }
.grid:not(.natural) table { height: 100%% }
th, td { border: .35mm solid #222; padding: .8mm 1.6mm; vertical-align: middle; overflow: hidden;
         overflow-wrap: anywhere }
.natural td, .natural th { height: 9mm }
thead th { background: #f0f1f3; font-weight: 600; text-align: center; height: 1px }
thead th:empty { height: 10mm }            /* a blank heading: room to write a name */
tbody th { text-align: left; font-weight: 600 }
td.x { background: repeating-linear-gradient(45deg, #cfd2d6 0 .45mm, #fff .45mm 1.8mm) }
img { max-width: 100%%; max-height: 40mm }
img.sym { height: 1.15em; width: auto; vertical-align: -.22em; max-height: none }
@media print { html, body { background: #fff } .page { margin: 0; box-shadow: none; break-after: page } }
"""


def render_sheet(sheet: Sheet, players: int | None = None) -> str:
    w, h = sheet.paper
    n = player_count(sheet, players)
    try:
        rounds = max(1, int(sheet.meta.get("rounds", 10)))
    except (TypeError, ValueError):
        rounds = 10
    try:
        font = float(sheet.meta.get("font_size", 11))
    except (TypeError, ValueError):
        font = 11.0
    fit = sheet.meta.get("fit", True) is not False
    base = sheet.path.parent
    pages: list[list[str]] = [[]]
    for b in sheet.blocks:
        if b.kind == "heading" and b.reopens:        # "---": a new page
            if b.quiet:
                continue
            pages.append([])
            continue
        if b.kind == "heading":
            lvl = min(b.level, 3)
            pages[-1].append(f"<h{lvl}>{inline(b.text, base)}</h{lvl}>")
        elif b.kind == "table":
            table, rows = render_table(b, base, n, rounds)
            cls = "grid" if fit else "grid natural"
            pages[-1].append(f'<div class="{cls}" style="--rows:{rows}">{table}</div>')
        elif b.kind == "image":
            pages[-1].append(f'<p><img src="{esc(data_uri(base, b.term))}" alt="{esc(b.text)}"></p>')
        elif b.kind == "item":
            pages[-1].append(f"<p>• {inline(b.text, base)}</p>")
        elif b.kind in ("para", "note", "key"):
            pages[-1].append(f"<p>{inline(b.text, base)}</p>")
    pages = [p for p in pages if p] or [[]]
    lang = esc(str(sheet.meta.get("language") or sheet.game_meta.get("language") or "fr"))
    css = SHEET_CSS % {"w": w, "h": h, "m": sheet.margin, "f": font}
    body = "".join(f'<section class="page">{"".join(p)}</section>' for p in pages)
    return (f'<!doctype html><html lang="{lang}"><head><meta charset="utf-8">'
            f'<meta name="viewport" content="width=device-width, initial-scale=1">'
            f"<title>{esc(sheet.title)}</title><style>{css}</style></head><body>{body}</body></html>\n")


def sheet_file_name(sheet: Path, slug: str | None, players: int | None = None) -> str:
    p = f"-{players}p" if players else ""
    if slug and sheet.stem != slug:
        return f"{slug}-{sheet.stem}{p}.html"
    return f"{sheet.stem}-sheet{p}.html"


# ------------------------------------------------------------------ command

def cmd_sheet(args) -> int:
    from .vault import open_vault
    words = args.name if isinstance(args.name, list) else ([args.name] if args.name else [])
    for w in [w for w in words if w.isdigit()]:              # "tabula sheet hearts 4": 4 players
        if args.players is None:
            args.players = int(w)
    names = [w for w in words if not w.isdigit()]
    args.name = names[0] if names else None
    target = Path(args.target)
    if target.suffix == ".sheet":
        if not target.is_file():
            raise SystemExit(f"tabula: no such sheet: {target}")
        if args.stdin:
            UNSAVED[target.resolve()] = sys.stdin.buffer.read().decode("utf-8", errors="replace")
        vault = open_vault(args.vault, str(target))
        paths = [target]
        g = game_file_for(target)
        slug = g.stem if g else None
    else:
        if args.stdin:
            raise SystemExit("tabula: --stdin needs the path of the .sheet file being edited")
        vault = open_vault(args.vault, args.target)
        g = vault.find(args.target)
        slug = g.stem
        paths = sheets_of(g, vault.root)
        if args.name:
            want = [p for p in paths if p.stem.lower() == args.name.lower()] or \
                   [p for p in paths if args.name.lower() in p.stem.lower()]
            if not want:
                raise SystemExit(f"tabula: no sheet '{args.name}' for {slug} "
                                 f"(sheets: {', '.join(p.stem for p in paths) or 'none'})")
            paths = want[:1]
        if not paths:
            raise SystemExit(f"tabula: {slug} has no score sheet (add a .sheet file next to {g.name})")
    if args.list:
        for p in paths:
            s = load_sheet(p, vault)
            w, h = s.paper
            print(f"{p.stem:<20} {s.title}  ({str(s.meta.get('size') or 'a4').upper()}, "
                  f"{'landscape' if w > h else 'portrait'})")
        return 0
    if args.output == "-":
        if len(paths) != 1:
            raise SystemExit("tabula: -o - needs a single sheet (name it after the game)")
        out = getattr(sys.stdout, "buffer", None)
        page = render_sheet(load_sheet(paths[0], vault), args.players)
        if out is not None:
            sys.stdout.flush()
            out.write(page.encode("utf-8"))
            out.flush()
        else:
            sys.stdout.write(page)
        return 0
    for p in paths:
        page = render_sheet(load_sheet(p, vault), args.players)
        dest = Path(args.output) if args.output else Path(sheet_file_name(p, slug, args.players))
        if dest.is_dir() or (args.output and len(paths) > 1):
            dest.mkdir(parents=True, exist_ok=True)
            dest = dest / sheet_file_name(p, slug, args.players)
        dest.write_text(page, encoding="utf-8")
        print(f"wrote {dest}")
    return 0
