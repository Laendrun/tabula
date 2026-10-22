# Changelog — Tabula Game Files (VS Code)

Newest first. VS Code shows this file in the extension's "Changelog" tab. Add your changes under
**Unreleased** as you go; when you bump `version` in `package.json`, rename that heading to the new version.

## Unreleased

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
