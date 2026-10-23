# Tabula for Neovim

Highlighting, and tabula's language server (`tabula lsp`) for Tabula `.game` and `.sheet` files, in Neovim 0.10 or newer.

- **Highlighting** of the frontmatter (as YAML), headings and `{#roles}`, `[[references]]` and `[[#section links]]`, `{conditions}` and `{choices | *: …}`, `{=values}`, `:symbols:`, component counts (`3x`), glossary terms and `key:: value` fields, `!` key rules and `## !` key sections, callouts `> [!type]`, `![[fragments]]`, tables (and the `{player}`, `{r}`, `//` cells of score sheets), `<!-- TODO -->` comments.
- **Everything else comes from the language server** `tabula lsp` (the same parser as every tabula command), through Neovim's own LSP client:
  - problems as you type (`tabula check`, unsaved text included) as diagnostics (`]d`, `[d`); TODO reminders are information;
  - completion as you type (Neovim 0.11; `<C-x><C-o>` before): `[[` terms and components (the included fragments' too), `[[#` sections and roles, `![[` fragments, `{=` values, `:` symbols, frontmatter keys and an extension's details;
  - **`K`** (hover): a reference's definition, a value, a symbol, a frontmatter key; **`gd`**: go to the definition (in the fragment file if it comes from one); `grr` references, `grn` rename, `gra` quick fixes (Neovim 0.11's default keys);
  - inlay hints (what `{=value}` stands for, totals, parts that don't add up), symbols (`gO`), folding, links, and "used N times" (code lens: `vim.lsp.codelens.refresh()` then `vim.lsp.codelens.run()`).
- **`:TabulaFormat`** tidies the buffer (`tabula fmt`, through the server); **`:TabulaPreview`** opens the game (or the score sheet) in your browser, with the player and extension filters; **`:TabulaCheck`** puts the problems in the quickfix list.

## Install

With [lazy.nvim](https://github.com/folke/lazy.nvim), add the repository like any plugin:

```lua
{ "Laendrun/tabula", opts = {} }       -- opts: see below (optional)
```

Other plugin managers work the same way (`Plug 'Laendrun/tabula'`, `use "Laendrun/tabula"`…): the repository's root is a plugin. Its `plugin/tabula.lua` adds this folder (`editors/nvim`) to Neovim's runtimepath and registers the `.game` and `.sheet` file types, and `lua/tabula` loads the module from here. Without a plugin manager, add the cloned repository to the runtimepath: `vim.opt.rtp:append("/path/to/tabula")`.

The plugin needs tabula with pygls: `pipx install ./cli` from the repository, then `pipx inject tabula pygls` (or set `cmd`). Without them, it says so once and only the highlighting works.

## Options

```lua
require("tabula").setup({
  cmd = { "tabula" },          -- how to run tabula, e.g. { "python3", "-m", "tabula" }
  spell = false,               -- also check spelling (tabula with spylls)
  definitions = false,         -- every component needs a glossary definition
  autocomplete = true,         -- completion menu as you type (Neovim 0.11+)
  format_on_save = false,      -- run tabula fmt when saving
  keymaps = true,              -- gd: go to the definition
})
```

With a completion plugin (nvim-cmp, blink.cmp…), its LSP source picks up tabula's completion; set `autocomplete = false`. Other editors with an LSP client (Helix, Zed, Sublime Text, Emacs…) can run `tabula lsp` the same way, for files ending in `.game` and `.sheet`.

## Tests

From the repository's root: `nvim --headless -u NONE -l editors/nvim/tests/test.lua` and `… tests/root.lua` (with `tabula` installed, or `TABULA_CMD="python3 -m tabula"` and `PYTHONPATH=cli`).
