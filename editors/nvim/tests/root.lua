-- The repository's root works as a plugin (what lazy.nvim and other plugin managers install):
--   nvim --headless -u NONE -l editors/nvim/tests/root.lua
local root = vim.fn.fnamemodify(debug.getinfo(1, "S").source:sub(2), ":p:h:h:h:h")
vim.opt.rtp:prepend(root)
vim.cmd("runtime! plugin/tabula.lua")          -- what a plugin manager does when it loads the plugin
vim.cmd("filetype plugin on")
vim.cmd("syntax on")
local cmd = vim.env.TABULA_CMD and vim.split(vim.env.TABULA_CMD, " ") or nil
require("tabula").setup({ spell = false, cmd = cmd })   -- lazy.nvim's `opts`
local dir = vim.fn.tempname()
vim.fn.mkdir(dir, "p")
vim.fn.writefile({ "name: T" }, dir .. "/vault.yaml")
local file = dir .. "/t.game"
vim.fn.writefile({ "---", "title: T", "players: 2", "---", "# Rules {#play}", "", "Draw a [[card]]." }, file)
vim.cmd.edit(file)
local attached = vim.wait(20000, function() return #vim.lsp.get_clients({ bufnr = 0, name = "tabula" }) > 0 end, 50)
local ok = vim.bo.filetype == "tabula" and vim.b.current_syntax == "tabula"
  and vim.fn.synIDattr(vim.fn.synID(7, 10, 1), "name") == "tabulaRef"
  and attached                                              -- the language server, from the repository's root
print(ok and "ok   the repository's root is a plugin" or "FAIL the repository's root is a plugin")
vim.fn.delete(dir, "rf")
os.exit(ok and 0 or 1)
