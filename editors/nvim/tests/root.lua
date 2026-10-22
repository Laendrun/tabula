-- The repository's root works as a plugin (what lazy.nvim and other plugin managers install):
--   nvim --headless -u NONE -l editors/nvim/tests/root.lua
local root = vim.fn.fnamemodify(debug.getinfo(1, "S").source:sub(2), ":p:h:h:h:h")
vim.opt.rtp:prepend(root)
vim.cmd("runtime! plugin/tabula.lua")          -- what a plugin manager does when it loads the plugin
vim.cmd("filetype plugin on")
vim.cmd("syntax on")
require("tabula").setup({ check = false })   -- lazy.nvim's `opts`
local file = vim.fn.tempname() .. ".game"
vim.fn.writefile({ "---", "title: T", "players: 2", "---", "# Rules {#play}", "", "Draw a [[card]]." }, file)
vim.cmd.edit(file)
local ok = vim.bo.filetype == "tabula" and vim.b.current_syntax == "tabula"
  and vim.bo.omnifunc == "v:lua.require'tabula'.omnifunc"
  and vim.fn.synIDattr(vim.fn.synID(7, 10, 1), "name") == "tabulaRef"
  and require("tabula").config.check == false
  and #require("tabula").items(vim.api.nvim_buf_get_lines(0, 0, -1, false), 3, 0, file) > 0   -- schemas found
print(ok and "ok   the repository's root is a plugin" or "FAIL the repository's root is a plugin")
vim.fn.delete(file)
os.exit(ok and 0 or 1)
