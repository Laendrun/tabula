# Tabula Game Files (VS Code)

Highlighting and live checks for Tabula `.game` files.

- **Checks while you type.** `tabula check` runs on the file you're editing, even before you save. Problems show up as squiggles and in the Problems panel (Ctrl+Shift+M). The squiggle goes on what the message is about, for example the `[[ref]]` that matches nothing. Translations of the same game (`slug.fr.game`) are checked at the same time.
- **Highlighting** for `[[references]]` and `[[#section links]]`, `{conditions}` and `{choices | *: …}`, `#roles`, component counts (`60x`), `key:: value` fields, `!` key rules and `## !` key sections, the `---` section end, player tables and the frontmatter.
- **Outline** (Explorer → Outline, or Ctrl+Shift+O): headings, glossary terms and components.
- **Ctrl+click / F12 on a `[[reference]]`** jumps to its definition, or to its component line. On a `[[#section link]]`, it jumps to the heading. In a translation, it also looks in the default-language file.
- **Folding** of sections and definitions.
- **Commands** (Ctrl+Shift+P): *Tabula: Check the whole vault* fills the Problems panel for every game. *Tabula: Check this game* checks the current file right away.

## Install

The extension needs tabula 0.7 or newer on your computer. If `tabula --version` works in a terminal, there's nothing more to set up.

Get the `.vsix` from GitHub: **Actions** tab → the latest green *tests* run → **Artifacts** → *vscode-extension*. It downloads as a zip; unzip it to get `tabula-game-files-<version>.vsix`, then:

```
code --install-extension tabula-game-files-0.2.0.vsix
```

Or, from VS Code: Extensions panel → `…` menu → *Install from VSIX…*.

The extension's ID is `tabula-rules.tabula-game-files`. If you installed an earlier build (ID `tabula.tabula`, which clashed with another extension on the Marketplace), remove it first: `code --uninstall-extension tabula.tabula`.

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
| `tabula.extraArgs` | `[]` | Arguments before `check`. To run the script from the repo without installing it: `tabula.path` = `python`, `tabula.extraArgs` = `["${workspaceFolder}/cli/tabula.py"]`. |
| `tabula.vault` | (found from the file) | The vault folder, if it can't be found automatically (it is found from the folder with `vault.yaml`, or the folder around the game's folder). |
| `tabula.run` | `onType` | `onType`: check after a short pause in typing. `onSave`: only when saving. |
| `tabula.delay` | `500` | The pause, in milliseconds. |
| `tabula.requireDefinitions` | `false` | Same as `tabula check -d`. |

If nothing happens, open *View → Output* and pick **Tabula** in the list: it shows the command that was run and its error.

## Development

```
cd editors/vscode
npm ci
npm test          # the logic and the grammar (with VS Code's own TextMate engine)
```

To try changes, open `editors/vscode` in VS Code and press F5. A second VS Code window opens with the extension loaded.
