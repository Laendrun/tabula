# Changelog — Tabula Game Files (VS Code)

Newest first. VS Code shows this file in the extension's "Changelog" tab. Add your changes under
**Unreleased** as you go; when you bump `version` in `package.json`, rename that heading to the new version.

## Unreleased

## 0.27.0 — 2026-10-23

### Changed
- The extension runs tabula's language server (`tabula lsp`) instead of calling tabula for every check and every hover: problems as you type, completion, hovers, go to definition, references, rename, quick fixes, formatting, the outline, folding, links, inline hints and use counts come from it, and answer at once.
- *Tabula: Restart the language server*. The `tabula.run` setting is gone (problems always show as you type).

Needs tabula 0.33 with pygls (`pipx inject tabula pygls`).

## 0.26.0 — 2026-10-23

### Changed
- One parser: the extension no longer reads .game files itself. Completion, hovers, go to definition, references, rename, use counts, the outline, folding, links, inline hints and quick fixes come from `tabula outline --json`, so they always agree with `tabula check` and the export (accents, plurals, comments, code blocks, fragments, translations).
- Columns are right after emoji and other characters that take two UTF-16 units.

Needs tabula 0.32: without it, only highlighting, snippets and the frontmatter key completion work.

## 0.25.0 — 2026-10-22

### Fixed
- References match plurals of three-letter words (`[[dés]]` → *Dé*), like tabula 0.31.

## 0.24.0 — 2026-10-22

### Fixed
- Security: `tabula.path` and `tabula.extraArgs` can only be set in your user settings: a folder's `.vscode/settings.json` could change the command run when a `.game` file is opened.

Needs tabula 0.30 for the safer previews (files outside the vault are no longer embedded).

## 0.23.0 — 2026-10-22

### Added
- Frontmatter keys: completion of the spec's keys (and of an extension's details, and a `.sheet`'s settings) with what they do, and a hover on each key (or "your own key").
- `vault.yaml` and `wishlist.yaml` are checked and completed by the Red Hat YAML extension, if installed, from the JSON Schemas of `spec/schemas`.

## 0.22.0 — 2026-10-22

### Added
- Totals: a field left empty in a group (`avec::` above `- [[Attaque 2x]]`…) shows what it adds up to, as an inline hint (`Σ 7 (base game: 4)`, each card in the tooltip) and in the hover.

Needs tabula 0.27.

## 0.21.0 — 2026-10-22

### Added
- Wishlist panel: a pack shows the wishes it contains under it.

Needs tabula 0.24.

## 0.20.0 — 2026-10-22

### Added
- A Tabula panel in the activity bar:
  - **Games**: each game with its player count and duration, ✓ or ⚠ from the checks, its translations and score sheets; click to open, buttons for the preview and to print the score sheet (for a chosen player count).
  - **Wishlist**: the wishes by priority; click to open `wishlist.yaml` at the wish; *Add to the wishlist* asks for the name, the game and the priority.
  - Buttons to check the vault, write the site (and open it in the browser) and write the book.
- Setting `tabula.siteFolder`.

### Fixed
- *Check the whole vault* no longer counts TODOs and unknown words as warnings.

Needs tabula 0.23.

## 0.19.0 — 2026-10-22

### Added
- Paste an image, or drop an image file from the explorer: it's copied to `media/` (`media/cards/<card>.png` on a card) and referenced: `image::` on a card (added or replaced), `![…](…)` elsewhere. An image already in the game's folder is just referenced.

### Changed
- Needs VS Code 1.97 or newer (for pasting).

## 0.18.0 — 2026-10-22

### Added
- Find all references (Shift+F12) to a term, component or section.
- "used N times" / "not used" above each definition, and above sections something links to (click to see where).
- Image paths (`image::`, `cover:`, `![…](…)`) and `![[fragments]]` are links (Ctrl+click); hovering an image path shows the picture.
- Inline hints: what each `{=value}` stands for, and "parts: 121 ≠ 125" when a component's parts don't add up.

## 0.17.0 — 2026-10-22

### Added
- The preview follows the cursor: it scrolls to the part of the rules you're editing (setting `tabula.previewFollowsCursor`).
- Double-click in the preview to put the cursor on that line.

Needs tabula 0.22.

## 0.16.0 — 2026-10-21

### Added
- `turn` in the role list of the `sec` snippet (for the turn summary).

## 0.15.0 — 2026-10-21

### Added
- Hovering a reference to a card with an `image::` field shows its picture.

## 0.14.0 — 2026-10-21

### Added
- Score sheets (`.sheet`): highlighting, live check, formatting and a preview of the printed page.
- `sheet` and `players` snippets.

## 0.13.0 — 2026-10-21

### Added
- Callouts: highlighting of `> [!type] Title`, `callout` snippet.

## 0.12.0 — 2026-10-21

### Added
- Symbols: highlighting, completion after `:x`, hover with the picture, `symbols` snippet.

## 0.11.0 — 2026-10-21

### Added
- Values: highlighting, completion after `{=`, hover; `val` and `values` snippets.

## 0.10.0 — 2026-10-21

### Added
- Snippets: `game`/`jeu`, `fm`, `sec`, `keysec`, `card`, `cards`, `ptable`, `choice`, `ref`, `inc`, `todo`…

## 0.9.0 — 2026-10-21

### Added
- Format Document (Shift+Alt+F) with `tabula fmt`; *Format this file* and *Format every file in the vault*.

### Fixed
- Formatting on Windows no longer adds a blank line after every line.

## 0.8.0 — 2026-10-21

### Added
- Quick fixes: closest terms for a reference that matches nothing, define it in the glossary, spelling, misspelt keys and roles.
- Rename (F2) a term, component or heading, with every reference to it.

## 0.7.0 — 2026-10-21

### Added
- Spell check (`tabula.spellCheck`): unknown words as information.

## 0.6.0 — 2026-10-21

### Added
- Live preview beside the editor (Ctrl+K V), with the player and option filters.
- Autocomplete, hover and Ctrl+click see terms from included fragments.

## 0.5.0 — 2026-10-20

### Added
- Shared fragments: `![[` completion, hover and Ctrl+click.

## 0.4.0 — 2026-10-20

### Added
- TODO reminders shown as information.

## 0.3.0 — 2026-10-20

### Added
- Autocomplete and hover for `[[references]]`.

## 0.2.0 — 2026-10-20

### Added
- Highlighting and checks while typing.
