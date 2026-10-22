# Changelog — tabula (CLI)

Newest first. Add your changes under **Unreleased** as you go; when you bump the version in
`cli/pyproject.toml` and `cli/tabula/_version.py`, rename that heading to the new version and date.
The format follows [Keep a Changelog](https://keepachangelog.com/): Added, Changed, Fixed.

## Unreleased

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
