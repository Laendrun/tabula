# Tabula for Neovim

Highlighting, completion, checks and formatting for Tabula `.game` and `.sheet` files, in Neovim 0.10 or newer.

- **Highlighting** of the frontmatter (as YAML), headings and `{#roles}`, `[[references]]` and `[[#section links]]`, `{conditions}` and `{choices | *: …}`, `{=values}`, `:symbols:`, component counts (`3x`), glossary terms and `key:: value` fields, `!` key rules and `## !` key sections, callouts `> [!type]`, `![[fragments]]`, tables (and the `{player}`, `{r}`, `//` cells of score sheets), `<!-- TODO -->` comments.
- **Completion** (the omni completion, `<C-x><C-o>`, opened by itself after `[[`, `[[#`, `![[`, `{=`, `:x` and at the start of a frontmatter line):
  - `[[` the glossary terms and components, including those of the shared fragments the game includes;
  - `[[#` the section titles and roles; `![[` the fragments in `_shared/`;
  - `{=` the values, `:` the symbols, of the game and `vault.yaml`;
  - in the frontmatter, the keys of the spec and, under `extensions:` → `name:`, an extension's details (from `spec/schemas`).
- **Checks:** `tabula check` runs on the buffer (unsaved text included) when you open it, save it, and after a pause in typing; its problems are diagnostics (`]d`, `[d`, `vim.diagnostic.open_float()`). TODO reminders are information, unknown words (with `spell = true`) hints.
- **`K`** on a `[[reference]]` shows its definition (or its component line, or the start of the section); **`gd`** goes there, in the fragment file if it comes from one. On `![[fragment]]`, `gd` opens the fragment.
- **`:TabulaFormat`** tidies the buffer with `tabula fmt`; **`:TabulaPreview`** opens the game (or the score sheet) in your browser, with the player and extension filters; **`:TabulaCheck`** checks now.

## Install

The plugin is the `editors/nvim` folder of this repository. With [lazy.nvim](https://github.com/folke/lazy.nvim):

```lua
{
  "Laendrun/tabula",
  config = function(plugin)
    vim.opt.rtp:append(plugin.dir .. "/editors/nvim")
    require("tabula").setup({})          -- see the options below
  end,
}
```

Without a plugin manager, clone the repository and add `vim.opt.rtp:append("/path/to/tabula/editors/nvim")` to your `init.lua`. Checks, formatting and the preview need the `tabula` command (`pipx install ./cli` from the repository).

## Options

```lua
require("tabula").setup({
  cmd = { "tabula" },          -- how to run tabula, e.g. { "python3", "-m", "tabula" }
  check = true,                -- run tabula check and show its problems as diagnostics
  check_on_change = true,      -- also while typing (after a pause), not only when saving
  debounce = 600,              -- ms of pause before checking while typing
  spell = false,               -- also check spelling (tabula with spylls)
  autocomplete = true,         -- open the completion menu by itself after [[, {=, :x…
  format_on_save = false,      -- run tabula fmt when saving
  keymaps = true,              -- K and gd in tabula buffers
})
```

With a completion plugin (nvim-cmp, blink.cmp…), add its *omni* source for the `tabula` filetype and set `autocomplete = false`.

## Tests

From the repository's root: `nvim --headless -u NONE -l editors/nvim/tests/test.lua` (with `tabula` installed, or `TABULA_CMD="python3 -m tabula"` and `PYTHONPATH=cli`).
