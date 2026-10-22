"""`tabula check`: finding mistakes in game files."""
from __future__ import annotations

import difflib
import json
import os
import re
import sys
from pathlib import Path

from .syntax import (
    BLOCK_COND_RE, BRACES_RE, CHOICE_RE, CONDISH_RE, Cond, FENCE_RE, FIELD_RE, HEADING_COND_RE,
    IMAGE_RE, KNOWN_ROLES, P_TOKEN, REF_RE, bounds, fold, in_range, parse_attrs, parse_choice, parse_cond,
    parse_range, split_lang,
)
from .fragments import SHARED_DIR, fragment_files
from .source import Issue, Issues, UNSAVED, find_todos
from .blocks import Block, components_of, is_sep_row, player_columns, player_rows
from .vault import Game, Vault, open_vault
from .terminal import Style, find_section
from .cards import card_catalog
from .spell import SpellError, check_spelling
from .values import value_problems
from .fields import GAME_KEYS
from .source import file_problem
from .totals import count_mismatches, empty_totals, members
from .options import option_problems, players_range, year_ok
from .sheet import check_sheet, load_sheet, sheets_of
from .wishlist import check_wishes
from .symbols import SYMBOL_RE, merged_symbols, symbol_problems

STRUCTURAL_KEYS = ("players", "best_players", "duration", "age", "year", "cover")
FRONTMATTER_KEYS = GAME_KEYS


def unique(iss: Issues) -> Issues:
    """Drop repeated issues: an included fragment can report the same problem twice at its `![[…]]` line."""
    out, seen = Issues(), set()
    for i in iss:
        key = (i.level, str(i.path), i.line, i.msg)
        if key not in seen:
            seen.add(key)
            out.append(i)
    return out


def check_game(game: Game, vault: Vault, require_defs: bool = False,
               unused: bool = True, fragment: bool = False) -> Issues:
    """Every problem in one game file. `fragment`: a shared fragment (_shared/…), checked on its own: no
    frontmatter needed, and conditions and references are only checked where the fragment is included."""
    iss = Issues()
    iss.extend(game.issues)
    path = game.body_path or game.path
    meta = game.meta

    # ---- frontmatter
    if fragment:
        pass
    elif not meta.get("title"):
        iss.error(path, 1, "missing required 'title' in frontmatter")
    if fragment:
        pass
    elif meta.get("players") is None:
        iss.error(path, 1, "missing required 'players' in frontmatter (e.g. players: 2-4)")
    elif parse_range(meta["players"]) is None:
        iss.error(path, 1, f"invalid players '{meta['players']}' (use N, N-M, N+ or N,M)")
    elif any(hi != float("inf") and hi > 100 for _, hi in parse_range(meta["players"])):
        iss.warn(path, 1, f"players '{meta['players']}': more than 100 players, is it a typo? (N+ means 'or more')")
    if meta.get("best_players") is not None and parse_range(meta["best_players"]) is None:
        iss.warn(path, 1, f"invalid best_players '{meta['best_players']}'")
    if meta.get("duration") is not None and parse_range(meta["duration"]) is None:
        iss.warn(path, 1, f"duration should be minutes, e.g. 30 or 30-60 (got '{meta['duration']}')")
    if meta.get("age") is not None and not str(meta["age"]).rstrip("+").isdigit():
        iss.warn(path, 1, f"age should be a number (got '{meta['age']}')")
    if meta.get("year") is not None and not year_ok(meta["year"]):
        iss.warn(path, 1, f"year should be the year the game came out, e.g. 2019 (got '{meta['year']}')")
    if meta.get("cover") and (why := file_problem(game.base_dir, str(meta["cover"]), vault.root)):
        iss.error(path, 1, f"cover image {why}: {meta['cover']}")
    v = meta.get("variants")
    if v is not None and not isinstance(v, (dict, list)):
        iss.error(path, 1, "'variants' must be a mapping (name: description) or a list of names")
    for key in ("rules",):
        if key in meta:
            iss.warn(path, 1, f"'{key}:' in frontmatter is from v0.3; move 'variants' (and others) to the top level")

    for key in (game.tr_meta if game.body_path != game.path else meta):
        # unknown keys are allowed (your own), but one close to a known key is probably a typo
        close = difflib.get_close_matches(str(key), [k for k in FRONTMATTER_KEYS if k not in meta], n=1, cutoff=0.8)
        if str(key) not in FRONTMATTER_KEYS and close:
            iss.warn(path, 1, f"'{key}:' in frontmatter: did you mean '{close[0]}'? (other keys are kept as they are)")

    own = game.tr_meta if game.body_path != game.path else meta
    for msg in value_problems(own.get("values")) + symbol_problems(own.get("symbols"), game.base_dir, vault.root):
        iss.error(path, 1, msg)

    for level, msg in option_problems(game):
        (iss.error if level == "error" else iss.warn)(path, 1, msg)

    game_rng = players_range(game, everything=True)          # extensions may add player counts
    declared = {k.lower() for k in game.options}
    ext = meta.get("extensions")
    if ext is not None and not isinstance(ext, (dict, list)):
        iss.error(path, 1, "'extensions' must be a mapping (name: description) or a list of names")
    for both in set(game.variants) & set(game.extensions):
        iss.warn(path, 1, f"'{both}' is declared both as a variant and as an extension")

    # ---- :symbols: that are probably misspelt (other :words: are left alone)
    names = list(merged_symbols(vault.root, game.base_dir, vault.config, meta))
    in_code = False
    for ln, t in game.lines:
        if FENCE_RE.match(t):
            in_code = not in_code
        if in_code or ":" not in t:
            continue
        for m in SYMBOL_RE.finditer(re.sub(r"`[^`]*`", "", t)):
            close = difflib.get_close_matches(m.group(1), names, n=1, cutoff=0.75)
            if close:
                iss.warn(path, ln, f"':{m.group(1)}:' is not a symbol: did you mean ':{close[0]}:'?")

    # ---- leftover v0.3 syntax (raw lines)
    in_code = False
    for ln, t in game.lines:
        if FENCE_RE.match(t):
            in_code = not in_code
        if in_code:
            continue
        if re.match(r"^=+\s", t):
            iss.warn(path, ln, "headings use '#' in v0.4 ('# Title', '## Sub'), not '='")
        if re.match(r"^\+\+\+ rules\s*$", t):
            iss.warn(path, ln, "'+++ rules' is no longer used (v0.4); just remove the line")
        if re.search(r"(?<![\w/&.])@[A-Za-zÀ-ÿ]", t):
            iss.warn(path, ln, "old '@component' syntax? v0.4 uses [[component]]")
        if re.search(r"(?<![\w/&#\[(])#[A-Za-zÀ-ÿ]", t) and not t.lstrip().startswith("#"):
            iss.warn(path, ln, "old '#keyword' syntax? v0.4 uses [[term]] and a definition")
        if "[p=" in t:
            iss.error(path, ln, "old '[p=…]' condition syntax; v0.4 uses {2p}, {3-4p: text | *: text}")
    if game.folder:
        for f in game.folder.glob("*.rules"):
            iss.warn(f, 0, "separate .rules files are not read in v0.4; move their content into the .game file")

    # ---- conditions
    def check_cond(c: Cond, ln, in_choice: bool = False):
        if not in_choice and any(k == "*" for k, _, _ in c.tokens):
            iss.error(path, ln, f"'{{{c.raw}}}': '*' (otherwise) only works inside an inline choice "
                                f"{{+x: … | *: …}}; for a line shown only without an option, write {{-name}}")
        for kind, neg, val in c.tokens:
            if kind == "p" and game_rng:
                lo, hi = bounds(game_rng)
                hits = [n for n in range(lo, int(min(hi, 99)) + 1) if in_range(game_rng, n) and in_range(val, n) != neg]
                if not hits:
                    iss.warn(path, ln, f"condition '{c.raw}' never applies (game is for {meta.get('players')} players)")
            elif kind == "v" and val not in declared and not fragment:
                iss.error(path, ln, f"'+{val}' is not declared; add it under 'variants:' or 'extensions:' "
                                    f"in the frontmatter")

    refs: list[tuple[str, int, str]] = []
    singles: list[tuple[str, int]] = []      # [name] with single brackets: maybe a mistyped [[name]]

    def check_text(text: str, ln: int, allow_block_cond: bool = False):
        rest = text
        if allow_block_cond and (m := BLOCK_COND_RE.match(rest)) and (c := parse_cond(m.group(1))):
            check_cond(c, ln)
            rest = rest[m.end():]
        for m in CHOICE_RE.finditer(rest):
            br = parse_choice(m.group(1))
            if br:
                for c, _ in br:
                    check_cond(c, ln, in_choice=True)
                if sum(1 for c, _ in br if any(k == "*" for k, _, _ in c.tokens)) > 1:
                    iss.warn(path, ln, "choice has more than one '*' alternative")
        for m in BRACES_RE.finditer(rest):
            body = m.group(1)
            if parse_choice(body) if ":" in body else False:
                continue
            if parse_cond(body):
                iss.error(path, ln, f"'{{{body}}}' in the middle of text: a block condition goes at the start or "
                                    f"the end of a line; inside a sentence write '{{{body}: text}}'")
            elif CONDISH_RE.search(body.split(":")[0]):
                iss.error(path, ln, f"invalid condition '{{{body}}}' (codes: 2p, 3-4p, 5+p, !2p, +variant, "
                                    f"-variant; choices: {{3p: … | *: …}})")
        for m in re.finditer(r"!\[\[([^\[\]\n]*)\]\]", rest):
            iss.error(path, ln, f"'{m.group(0)}' includes a shared fragment only when it is alone on its line")
        for m in REF_RE.finditer(rest):
            if m.start() and rest[m.start() - 1] == "!":
                continue          # a misplaced ![[fragment]], reported above
            refs.append((m.group(1).strip(), ln, m.group(0)))
        for m in re.finditer(r"(?<![\[!\\])\[([^\[\]\n]+)\](?![\](\[])", REF_RE.sub("", rest)):
            singles.append((m.group(1).strip(), ln))
        if (nm := re.search(r"(?<!\\)\[\[([^\[\]\n]*)\[\[([^\[\]\n]*)\]\]", rest)):
            inner = f"{nm.group(1).strip()} {nm.group(2).strip()}".strip()
            iss.error(path, ln, f"a reference inside another reference: write [[{inner}]] "
                                f"(section links ignore the brackets in the heading)")
        elif re.search(r"(?<!\\)\[\[(?![^\]]*\]\])", REF_RE.sub("", rest)):
            iss.error(path, ln, "unclosed '[[' reference")
        for m in IMAGE_RE.finditer(rest):
            src = m.group(2)
            if why := file_problem(game.base_dir, src, vault.root):
                iss.error(path, ln, f"image {why}: {src}")

    terms: dict[str, tuple[int, str]] = {}
    bracketed: set[str] = set()      # terms written as [[Term]]: reported once, not at every reference

    def walk(blocks: list[Block]):
        for b in blocks:
            if b.kind == "heading" and b.reopens:
                continue          # "---": its condition belongs to the section it reopens
            if b.cond:
                check_cond(b.cond, b.line)
            if b.kind == "heading":
                if (cm := HEADING_COND_RE.search(b.text)) and not parse_attrs(cm.group(1)):
                    iss.error(path, b.line, f"invalid heading attributes '{{{cm.group(1)}}}' (roles look like "
                                            f"#glossary, conditions like 2p or +name)")
                    continue
                for role in b.roles:
                    close = difflib.get_close_matches(role, KNOWN_ROLES, n=1, cutoff=0.7)
                    if role not in KNOWN_ROLES and close:
                        iss.warn(path, b.line, f"role '#{role}': did you mean '#{close[0]}'? Tools only know "
                                               f"'#{close[0]}' (your own role names are fine otherwise)")
                check_text(b.text, b.line)
            elif b.kind == "note" and b.children:      # paragraphs or a list inside a quote
                walk(b.children)
            elif b.kind in ("para", "item", "note", "key"):
                src = b.src or [(b.line, b.text)]
                for k, (ln, raw) in enumerate(src):
                    if k == 0:   # the block condition / "!" were already taken off b.text
                        raw = raw.lstrip("! ")
                        if (m := BLOCK_COND_RE.match(raw)) and parse_cond(m.group(1)):
                            raw = raw[m.end():].lstrip("! ")
                    if k == len(src) - 1 and (m := HEADING_COND_RE.search(raw)) and parse_cond(m.group(1)):
                        raw = raw[: m.start()]       # condition written at the end of the block
                    check_text(raw, ln)
                if re.sub(r"`[^`]*`|\\\*", "", b.text).count("**") % 2:
                    iss.warn(path, b.line, "'**' is opened but never closed (bold text needs '**' on both sides)")
            elif b.kind == "image":
                if why := file_problem(game.base_dir, b.term, vault.root):
                    iss.error(path, b.line, f"image {why}: {b.term}")
            elif b.kind == "def":
                if (rm := REF_RE.fullmatch(b.term)):
                    iss.error(path, b.line, f"term '{b.term}' is written as a reference; "
                                            f"write it without brackets: '{rm.group(1).strip()}'")
                    bracketed.add(fold(rm.group(1)))
                k = fold(b.term)
                if k in terms:
                    iss.warn(path, b.line, f"'{b.term}' is defined twice (also line {terms[k][0]})")
                else:
                    terms[k] = (b.line, b.term)
                if not b.children and not b.fields:
                    iss.warn(path, b.line, f"definition of '{b.term}' is empty")
                for key, val in b.fields.items():
                    if not val:
                        if key in empty_totals(b, game.blocks):
                            iss.warn(path, b.field_lines.get(key, b.line),
                                     f"field '{key}' of '{b.term}' is empty" + (
                                         f", and none of the cards it lists has a '{key}' to add up"
                                         if members(b) else
                                         " (an empty field is a total: list the cards to add up, '- [[Card]]')"))
                    elif key == "image":           # a card's picture
                        src = val.strip()
                        if why := file_problem(game.base_dir, src, vault.root):
                            iss.error(path, b.field_lines.get(key, b.line), f"picture of '{b.term}' {why}: {src}")
                    else:
                        check_text(val, b.field_lines.get(key, b.line))
                for key, ln in b.field_lines.get("__dup__", []):
                    iss.warn(path, ln, f"field '{key}' is written twice in '{b.term}'")
                for kid in b.children:
                    if kid.kind == "para" and FIELD_RE.match(kid.text) and not kid.level:
                        iss.warn(path, kid.line, f"'{kid.text.split('::')[0]}::' looks like a field but is below the "
                                                 f"text of '{b.term}'; fields go on the first lines of a definition")
                walk(b.children)
            elif b.kind == "table":
                cols = player_columns(b)
                header = b.rows[0][1] if b.rows else []
                if not cols and len(header) > 1 and any(P_TOKEN.match(c.strip()) for c in header[1:]):
                    iss.error(path, b.line, "table mixes player codes and other headers; for a player table every "
                                            "header after the first must be a code like 3p, 4-5p, 6+p")
                body = [cells for _, cells in b.rows[1:] if not is_sep_row(cells)]
                if (not cols and not player_rows(b) and body
                        and all(c and re.fullmatch(r"\d+(-\d+|\+)", c[0].strip()) for c in body)):
                    iss.warn(path, b.line, f"first column looks like player counts ('{body[0][0].strip()}'); "
                                           f"write '{body[0][0].strip()}p' so tables are filtered by player count")
                if len({len(c) for _, c in b.rows}) > 1:
                    iss.warn(path, b.line, "table rows have different numbers of cells")
                for ln, cells in b.rows:
                    for j, c in enumerate(cells):
                        check_text(c, ln, allow_block_cond=(j == 0))

    walk(game.blocks)

    # ---- groups: their count in the components and their cards' counts
    if not fragment:
        for g, msg in count_mismatches(game):
            iss.warn(path, g.line, msg)

    # ---- card catalog: a field most cards of a group have, but this one doesn't
    groups: dict[str, list[Block]] = {}
    for c in card_catalog(game.blocks):
        groups.setdefault(c["group"], []).append(c["def"])
    for gname, cards in groups.items():
        if len(cards) < 3:
            continue
        keys = {k for d in cards for k in d.fields} - {"image"}     # pictures are optional
        for k in sorted(keys):
            have = sum(1 for d in cards if k in d.fields)
            if have * 2 > len(cards):
                for d in cards:
                    if k not in d.fields:
                        iss.warn(path, d.line, f"card '{d.term}' has no '{k}::' field ({have} of {len(cards)} cards "
                                               f"in '{gname or 'cards'}' have one)")

    # ---- references
    known = {fold(c["name"]) for c in components_of(game.blocks)} | set(terms) | bracketed
    if require_defs:      # every component must also be described in the glossary
        reported_defs = set()
        for c in components_of(game.blocks):
            k = fold(c["name"])
            if k not in terms and k not in bracketed and k not in reported_defs:
                reported_defs.add(k)
                iss.warn(path, c["line"], f"component '{c['name']}' has no definition; add '{c['name']}' "
                                          f"then ': …' to the glossary")
    for name, ln in singles:
        if fold(name) in known:
            iss.warn(path, ln, f"'[{name}]' has single brackets; write [[{name}]] to make it a reference")
    seen = set()
    if fragment:          # references and unused terms depend on the game that includes it
        for ln, text in find_todos(path):
            iss.todo(path, ln, f"TODO: {text}")
        return unique(iss)

    # ---- definitions nothing refers to (cards in a catalog are listed there, so they don't count)
    if unused:
        referenced = {fold(name) for name, _, _ in refs if not name.startswith("#")}
        cards = {id(c["def"]) for c in card_catalog(game.blocks)}

        def defs(blocks):
            for b in blocks:
                if b.kind == "def":
                    yield b
                    yield from defs(b.children)
        reported = set()
        for d in defs(game.blocks):
            k = fold(d.term)
            if id(d) in cards or k in referenced or k in reported or REF_RE.fullmatch(d.term):
                continue
            reported.add(k)
            iss.warn(path, d.line, f"'{d.term}' is defined but nothing refers to it; link to it with [[{d.term}]] "
                                   f"or remove it")

    # ---- reminders left in the file
    for ln, text in find_todos(path):
        iss.todo(path, ln, f"TODO: {text}")

    for name, ln, raw in refs:
        if name.startswith("#"):
            if not find_section(game.blocks, name):
                iss.warn(path, ln, f"{raw} matches no section (a heading titled '{name[1:].strip()}', "
                                   f"or a role like #setup)")
            continue
        k = fold(name)
        if k not in known and k not in seen:
            seen.add(k)
            iss.warn(path, ln, f"{raw} matches no component ('- 1x [[{name}]]' in a list) and no definition "
                               f"('{name}' then ': …')")
    return unique(iss)


def check_translation(default: Game, tr: Game, vault: Vault, require_defs: bool = False,
                      unused: bool = True) -> Issues:
    iss = Issues()
    tp = tr.body_path
    for i in check_game(tr, vault, require_defs=require_defs, unused=unused):
        if Path(i.path) == tp and not i.msg.startswith(("cover image",)):
            iss.append(i)
    declared = tr.tr_meta.get("language")
    if declared and declared != tr.language:
        iss.warn(tp, 1, f"language '{declared}' in frontmatter doesn't match the file name ('.{tr.language}.')")
    for k in STRUCTURAL_KEYS:
        if k in tr.tr_meta and str(tr.tr_meta[k]) != str(default.meta.get(k)):
            iss.warn(tp, 1, f"'{k}' differs from the default language ({tr.tr_meta[k]} vs {default.meta.get(k)}); "
                            "leave it out so it is inherited")
    for key, ref in (("variants", default.variants), ("extensions", default.extensions)):
        if not isinstance(tr.tr_meta.get(key), dict):
            continue
        extra = set(tr.tr_meta[key]) - set(ref)
        if extra:
            iss.warn(tp, 1, f"{key} {', '.join(sorted(extra))} not declared in the default language; "
                            "keep the names identical and translate only their descriptions")
    return iss


def rel(p: Path, vault: Vault) -> str:
    try:
        return str(Path(p).resolve().relative_to(vault.root))
    except ValueError:
        return str(p)


def cmd_check(args) -> int:
    if args.stdin:
        if len(args.games) != 1 or not Path(args.games[0]).is_file():
            raise SystemExit("tabula: --stdin needs exactly one .game or .sheet file (the file being edited)")
        UNSAVED[Path(args.games[0]).resolve()] = sys.stdin.buffer.read().decode("utf-8", errors="replace")
    vault = open_vault(args.vault, args.games[0] if args.games else None)
    if args.games and all(g.endswith(".sheet") for g in args.games):        # score sheets on their own
        return check_sheets(vault, [Path(g) for g in args.games], args)
    paths = [vault.find(g) for g in args.games] if args.games else vault.discover() + shared_fragments(vault)
    if args.json:
        return check_json(vault, paths, args)
    st = Style(sys.stdout.isatty() and not os.environ.get("NO_COLOR") and not args.no_color)
    te = tw = 0

    def show(i: Issue, indent="  "):
        loc = rel(i.path, vault) + (f":{i.line}" if i.line else "")
        lvl = (st.red("error  ") if i.level == "error" else st.dim("spelling") if i.level == "spelling"
               else st.yellow("warning"))
        print(f"{indent}{lvl}  {loc}  {i.msg}")

    tt = ts = 0

    if not args.games:
        vault_issues = list(vault.issues) + list(check_wishes(vault))      # vault.yaml, wishlist.yaml
        for i in vault_issues:
            show(i, "")
        te += sum(i.level == "error" for i in vault_issues)
        tw += sum(i.level == "warning" for i in vault_issues)
    for p in paths:
        game, iss = check_all_languages(vault, p, args.definitions, args.spell)
        todos = [i for i in iss if i.level == "todo"]
        words = [i for i in iss if i.level == "spelling"]
        iss = [i for i in iss if i.level not in ("todo", "spelling")]
        e = sum(i.level == "error" for i in iss)
        w = len(iss) - e
        te, tw, tt, ts = te + e, tw + w, tt + len(todos), ts + len(words)
        status = st.green("ok") if not iss else ", ".join(
            x for x in (st.red(f"{e} error(s)") if e else "", st.yellow(f"{w} warning(s)") if w else "") if x)
        if words:
            status += st.dim(f"  ({len(words)} unknown word(s))")
        if todos:
            status += st.dim(f"  ({len(todos)} TODO)")
        langs = f"  [{', '.join(game.languages)}]" if len(game.languages) > 1 else ""
        name = f"{SHARED_DIR}/{game.slug}" if p.parent.name == SHARED_DIR else game.slug
        print(f"{st.bold(name):<30} {status}{st.dim(langs)}")
        for i in iss + words:
            show(i)
    todo_note = f", {tt} TODO (tabula todo)" if tt else ""
    if ts:
        todo_note += (f", {ts} unknown word(s) (if they're right: words.txt in the vault, or 'words:' in "
                      f"the frontmatter)")
    nfrag = sum(1 for p in paths if p.parent.name == SHARED_DIR)
    counted = f"{len(paths) - nfrag} game(s)" + (f", {nfrag} fragment(s)" if nfrag else "")
    print(f"\n{counted}, {te} error(s), {tw} warning(s){todo_note}")
    return 1 if te or (args.strict and tw) else 0


def check_setting(vault: Vault, game: Game, key: str, default: bool) -> bool:
    """A check option from the game's frontmatter, else vault.yaml's `check:`, else the default."""
    if key in game.meta:
        return bool(game.meta[key])
    cfg = vault.config.get("check")
    return bool(cfg.get(key, default) if isinstance(cfg, dict) else default)


def shared_fragments(vault: Vault) -> list[Path]:
    """The default-language files in _shared/ (translations are checked with them)."""
    return [f for f in fragment_files(vault.root) if split_lang(f.stem)[1] is None]


_spell_failed: set = set()


def spelling(game: Game, vault: Vault, lang: str | None = None) -> Issues:
    """The unknown words of one file, as "spelling" issues (a missing dictionary is one warning per run)."""
    iss = Issues()
    path = game.body_path or game.path
    try:
        for ln, msg in check_spelling(game, vault, lang):
            iss.spelling(path, ln, msg)
    except SpellError as e:
        if str(e) not in _spell_failed:
            _spell_failed.add(str(e))
            iss.warn(path, 1, f"spell check: {e}")
    return iss


def check_fragment(vault: Vault, p: Path, spell: bool = False) -> tuple[Game, list[Issue]]:
    """A shared fragment and its translations, each checked on its own."""
    game = vault.load(p)
    cfg = vault.config.get("check")
    spell = spell or bool(isinstance(cfg, dict) and cfg.get("spelling", False))
    iss = list(check_game(game, vault, fragment=True))
    if spell:
        iss += spelling(game, vault, str(game.meta.get("language") or vault.language))
    for f in p.parent.glob(f"{p.stem}.*.game"):
        if (lang := split_lang(f.stem))[0] == p.stem:
            tr = vault.load(f)
            iss += check_game(tr, vault, fragment=True)
            if spell:
                iss += spelling(tr, vault, lang[1])
    iss.sort(key=lambda i: (str(i.path), i.line))
    return game, iss


def check_all_languages(vault: Vault, p: Path, definitions: bool, spell: bool = False) -> tuple[Game, list[Issue]]:
    if p.parent.name == SHARED_DIR:
        return check_fragment(vault, p, spell)
    game = vault.load(p)
    req = definitions or check_setting(vault, game, "require_definitions", False)
    unused = check_setting(vault, game, "unused_definitions", True)
    spell = (spell and game.meta.get("spelling") is not False) or check_setting(vault, game, "spelling", False)
    iss = list(check_game(game, vault, require_defs=req, unused=unused))
    if spell:
        iss += spelling(game, vault)
    for lang in game.languages:
        if lang != game.default_language:
            tr = vault.load(p, lang)
            iss += check_translation(game, tr, vault, require_defs=req, unused=unused)
            if spell:
                iss += spelling(tr, vault)
    for s in sheets_of(p, vault.root):                 # its score sheets
        iss += check_sheet(load_sheet(s, vault), vault)
    iss.sort(key=lambda i: (str(i.path), i.line))
    return game, iss


def check_sheets(vault: Vault, paths: list[Path], args) -> int:
    """tabula check x.sheet: only those sheets (text, or --json for editors)."""
    found = []
    for p in paths:
        if not p.is_file():
            raise SystemExit(f"tabula: no score sheet {p}")
        found += check_sheet(load_sheet(p, vault), vault)
    errors = sum(i.level == "error" for i in found)
    warnings = sum(i.level == "warning" for i in found)
    if args.json:
        print(json.dumps({"vault": str(vault.root), "files": [str(p.resolve()) for p in paths],
                          "issues": [{"path": str(Path(i.path).resolve()), "line": i.line, "level": i.level,
                                      "message": i.msg} for i in found]}, indent=2))
    else:
        for i in found:
            print(f"  {i.level:<8} {rel(i.path, vault)}:{i.line}  {i.msg}")
        print(f"\n{len(paths)} sheet(s), {errors} error(s), {warnings} warning(s)")
    return 1 if errors or (args.strict and warnings) else 0


def check_json(vault: Vault, paths: list[Path], args) -> int:
    """check --json: every issue with an absolute path, for editors and scripts."""
    found = list(vault.issues) + list(check_wishes(vault)) if not args.games else []
    files = []
    for p in paths:
        game, iss = check_all_languages(vault, p, args.definitions, args.spell)
        found += iss
        files += [str(p.parent / (f"{game.slug}.game" if lang == game.default_language else f"{game.slug}.{lang}.game"))
                  for lang in game.languages]
        files += [str(s) for s in sheets_of(p, vault.root)]
    out = {"vault": str(vault.root), "files": files,
           "issues": [{"path": str(Path(i.path).resolve()), "line": i.line, "level": i.level, "message": i.msg}
                      for i in found]}
    print(json.dumps(out, indent=2))
    errors = sum(i.level == "error" for i in found)
    warnings = sum(i.level == "warning" for i in found)
    return 1 if errors or (args.strict and warnings) else 0
