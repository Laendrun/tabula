# Changelog — tabula (CLI)

Newest first. Add your changes under **Unreleased** as you go; when you bump the version in
`cli/pyproject.toml` and `cli/tabula/_version.py`, rename that heading to the new version and date.
The format follows [Keep a Changelog](https://keepachangelog.com/): Added, Changed, Fixed.

## Unreleased

## 0.30.0 — 2026-10-22

### Fixed
- Security: a game could make the exported page, the site, the book and score sheets embed any file of the computer (`![x](/etc/passwd)`, `image:: ../../.ssh/id_rsa`, `cover:`, a symbol). Only files inside the vault are read now, and `tabula check` reports the others ("outside the vault").
- Security: `[x](javascript:…)` (and `data:`, `vbscript:`…) links ran scripts in the pages; only web, mail and phone addresses, `game:` links and relative paths are links now. The same for a wish's `link:`.
- Security: `language:` was put in pages and file names as it was; it must be a language code now (check reports it, the vault's language is used instead).
- `![[../../x]]` included a file from anywhere: fragments are names in `_shared/` only.
- `tabula new bgg ID ../x` wrote outside the vault: a game's name can't be a path.
- A NUL character in a file made the export, the site, the book and the VS Code preview run forever; it is dropped, with a warning.
- `tabula fmt` rewrote files that aren't UTF-8 (Latin-1…) and lost their accents for good; it leaves them as they are now, and `tabula check` says the file isn't UTF-8 instead of failing.

## 0.29.0 — 2026-10-22

### Added
- `tabula check` warns when a group's count in the components (`- 10x [[Attaque]]`) differs from the counts of the cards it lists added up, in the base game, with every extension and variant, or with one of them.

## 0.28.0 — 2026-10-22

### Added
- `tabula cards` and the catalog table list a group's cards under it, indented, and mark the group with Σ; groups aren't counted as cards. `cards --json` adds `kind` (card or group) and a group's `cards`.

## 0.27.0 — 2026-10-22

### Added
- Totals: a field left empty in a definition that lists cards (`avec::` above `- [[Attaque 2x]]`, `- {+barking} [[…]]`) is the sum of that field on those cards, for the chosen extensions and player count. It updates on the interactive page, and works in `show`, `lookup`, `cards`, the exports and JSON.

### Changed
- `tabula check` no longer warns about an empty field that is a total; it says so when nothing listed has that field.

## 0.26.0 — 2026-10-22

### Added
- Your own frontmatter keys (`series:`, `bought_at:`…) are shown as "Label: value" on the exported page, in the book and in `tabula show`.
- `year:` is shown: on the game's page (next to the credits), in `tabula show`, on the site's game cards and in `list --json`.
- Extensions and variants can have a `year` and your own details; they are listed with their details in the page's header ("Extensions and variants"), in the checkbox tooltips and in `tabula show`.
- `tabula check` warns about a `year` that isn't a year.

### Changed
- An unknown extension or variant detail is no longer an error: it is your own. Only one that looks like a typo of a known detail gets a warning.

## 0.25.0 — 2026-10-22

### Added
- Paragraphs and lists inside callouts and notes: a `>` line alone separates paragraphs, `> - …` makes a list (items continue on indented lines). Conditions work on each paragraph or item.

## 0.24.0 — 2026-10-22

### Added
- Wishlist packs: `in: "Pack name"` on a wish that is also in another one; the pack is listed with its parts ("or separately") in `tabula wish`, on the site and in VS Code, and removing it removes its parts. `tabula wish add --in PACK`.

### Changed
- A wish's `for:` can be the game's title as well as its slug (case and accents ignored).
- A YAML error about `: ` in a value says to add quotes.

## 0.23.0 — 2026-10-22

### Added
- `tabula list --json`: the games with their paths, translations, score sheets and cover (used by the VS Code panel).

## 0.22.0 — 2026-10-22

### Added
- `tabula export --lines` marks each block with its line in the file (used by the VS Code preview to follow the cursor).

## 0.21.1 — 2026-10-22

### Fixed
- Spell check skips `image::` values and file paths (`media/cards/gift.png`).
- A card without a picture is no longer a warning (pictures are optional; a missing file is still an error).
- Callouts and notes sit beside a card's picture instead of under it.

## 0.21.0 — 2026-10-22

### Added
- Wishlist: `wishlist.yaml` at the vault's root (name, `for:` an extension's game, priority, price, link, note).
- `tabula wish` lists it; `tabula wish add "Name" --for GAME --priority N` and `tabula wish remove "Name"` change it.
- `tabula check` checks the wishlist; `tabula site` writes a wishlist page and links games to their wished extensions.

## 0.20.0 — 2026-10-21

### Added
- Extension and variant details: `players`, `duration`, `needs`, `excludes`.
- `-p 10 -e pandora` works when the extension adds player counts; `list -p` and the site's filter find the game.
- `needs` turns the other option on; `excludes` refuses both together. `check` reports invalid details.

## 0.19.0 — 2026-10-21

### Added
- Turn summary: the `#turn` role; `tabula show/export GAME --turn`; a "Résumé du tour" page on the site.
- `tabula export --paper a4|a5|a6|letter` sets the printed page size.

## 0.18.0 — 2026-10-21

### Added
- Card pictures: an `image::` field, drawn on the card (site, export, book) and in the catalog table.

## 0.17.0 — 2026-10-21

### Added
- Score sheets: `.sheet` files next to a game; `{player}` columns, `{r}` rounds, `//` shaded and `<` `^` merged cells.
- `tabula sheet GAME [-p N]` writes print-ready pages the size of the paper; `check`, `fmt` and `site` support sheets.

## 0.16.0 — 2026-10-21

### Added
- Callouts: `> [!exemple] Title`, `[!attention]`, `[!astuce]`, `[!précision]`, `[!question]`… drawn by family.

## 0.15.0 — 2026-10-21

### Added
- Symbols: `:gold:`, defined in `vault.yaml` or a game's frontmatter (text or image).

### Fixed
- Symbols right after a number (`3:gold:`).

## 0.14.0 — 2026-10-21

### Added
- Values: `{=main}`, defined in `vault.yaml` or the frontmatter, by player count or option.
- Choices in player-table cells are shown for their column's player count.

### Fixed
- A `|` inside an inline choice no longer splits table cells.

## 0.13.0 — 2026-10-21

### Added
- `tabula fmt`: tidy files (blank lines, aligned tables, spaces) without ever changing what they say.

### Fixed
- A `|` inside `[[a|b]]` no longer splits table cells or choices; `\|` is a literal `|` in a cell.
- `fmt --stdin` and `export -o -` on Windows: no blank line after every line.

## 0.12.0 — 2026-10-21

### Added
- `tabula check --spell`: Hunspell spell check in each file's language (optional `spylls` package).
- Warnings for a misspelt frontmatter key or role (`durantion:`, `#cartes`).

## 0.11.0 — 2026-10-21

### Added
- `tabula export --interactive` and `--stdin` (used by the VS Code preview); a translation is exported in its language.

## 0.10.0 — 2026-10-21

### Added
- `tabula book`: games as an EPUB book.

## 0.9.1 — 2026-10-21

### Changed
- Consecutive `!` lines make one key rule.

## 0.9.0 — 2026-10-21

### Added
- Site: choose players and extensions on a game's page.

## 0.8.2 — 2026-10-21

### Added
- The cover is found by its name: `media/cover.*` or `media/<slug>_cover.*`.

## 0.8.1 — 2026-10-21

### Added
- Card fields can continue on indented lines.

## 0.8.0 — 2026-10-20

### Added
- Shared fragments: `![[deck-52]]` includes `_shared/deck-52.game`.

## 0.7.0 — 2026-10-20

### Changed
- The single `tabula.py` script became a package of modules. Earlier versions: see the git history.
