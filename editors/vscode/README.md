# Tabula Game Files (VS Code)

Highlighting, live checks and a live preview for Tabula `.game` files.

- **Live preview.** Click the preview button in the editor's title bar, or press Ctrl+K V (Cmd+K V on a Mac). The game opens beside the editor as `tabula site` renders it, with the player and option filters. It updates as you type (before you save), follows the `.game` file you switch to, and keeps your filter choice and scroll position. Links to other games open their file, web links open in your browser.
- **Checks while you type.** `tabula check` runs on the file you're editing, even before you save. Problems show up as squiggles and in the Problems panel (Ctrl+Shift+M). The squiggle goes on what the message is about, for example the `[[ref]]` that matches nothing. Translations of the same game (`slug.fr.game`) are checked at the same time. `<!-- TODO: … -->` reminders show up as information (blue), not as warnings.
- **Highlighting** for `[[references]]` and `[[#section links]]`, `{conditions}` and `{choices | *: …}`, `#roles`, component counts (`60x`), `key:: value` fields, `!` key rules and `## !` key sections, the `---` section end, player tables and the frontmatter.
- **Autocomplete inside `[[ ]]`.** Type `[[` to pick a glossary term or component, including those of the shared fragments the game includes with `![[…]]` (definitions first, with their text as a preview). Type `[[#` to pick a section title or a role like `setup`. The closing `]]` is added when it's missing.
- **Hover a `[[reference]]`** (also one defined in an included fragment) to see its definition (fields included), its component lines, or the start of the section it links to. In a translation, terms missing from the file are looked up in the default-language file.
- **Outline** (Explorer → Outline, or Ctrl+Shift+O): headings, glossary terms and components.
- **Ctrl+click / F12 on a `[[reference]]`** jumps to its definition, or to its component line, in the fragment file if that's where it comes from. On a `[[#section link]]`, it jumps to the heading. In a translation, it also looks in the default-language file.
- **Shared fragments:** `![[` offers the fragments in the vault's `_shared/` folder, and `![[deck-52#` their sections. Ctrl+click opens the fragment at that section (the translated one in a translation), and hovering previews what is included.
- **Folding** of sections and definitions.
- **Commands** (Ctrl+Shift+P): *Tabula: Check the whole vault* fills the Problems panel for every game. *Tabula: Check this game* checks the current file right away.

## Install

The extension needs tabula 0.8 or newer (0.11 for the preview) on your computer. If `tabula --version` works in a terminal, there's nothing more to set up.

Get the `.vsix` from GitHub: **Actions** tab → a green *tests* run → **Artifacts** → *vscode-extension*. It downloads as a zip; unzip it to get `tabula-syntax-<version>.vsix`, then:

```
code --install-extension tabula-syntax-<version>.vsix
```

Or, from VS Code: Extensions panel → `…` menu → *Install from VSIX…*. Installing a newer `.vsix` the same way replaces the old version.

The extension's ID is `Laendrun.tabula-syntax`. If you installed an earlier build, remove it first: `code --uninstall-extension tabula-rules.tabula-game-files` (or `tabula.tabula` for the very first ones).

To build the `.vsix` yourself (Node.js needed):

```
cd editors/vscode
npm ci
npm run package
```

## Settings

| Setting | Default | |
|---|---|---|
| `tabula.path` | `tabula` | The command. If `tabula` isn't on your PATH, the full path to `tabula.exe`, e.g. `C:\Users\you\.local\bin\tabula.exe`. |
| `tabula.extraArgs` | `[]` | Arguments before `check` (and `export`, for the preview). To run the script from the repo without installing it: `tabula.path` = `python`, `tabula.extraArgs` = `["${workspaceFolder}/cli/tabula"]`. |
| `tabula.vault` | (found from the file) | The vault folder, if it can't be found automatically (it is found from the folder with `vault.yaml`, or the folder around the game's folder). |
| `tabula.run` | `onType` | `onType`: check after a short pause in typing. `onSave`: only when saving. |
| `tabula.delay` | `500` | The pause, in milliseconds (checks and preview). |
| `tabula.requireDefinitions` | `false` | Same as `tabula check -d`. |

If nothing happens, open *View → Output* and pick **Tabula** in the list: it shows the command that was run and its error.

## Development

```
cd editors/vscode
npm ci
npm test          # the logic and the grammar (with VS Code's own TextMate engine)
```

To try changes, open `editors/vscode` in VS Code and press F5. A second VS Code window opens with the extension loaded.
