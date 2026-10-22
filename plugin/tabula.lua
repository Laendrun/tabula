-- Neovim plugin loader, so that plugin managers (lazy.nvim: { "Laendrun/tabula" }) can install this
-- repository as it is. The plugin itself is in editors/nvim; this adds it to the runtimepath.
if vim.g.loaded_tabula then return end
vim.g.loaded_tabula = 1

local root = vim.fn.fnamemodify(debug.getinfo(1, "S").source:sub(2), ":p:h:h")
local dir = root .. "/editors/nvim"
if not vim.tbl_contains(vim.opt.rtp:get(), dir) then
  vim.opt.rtp:append(dir)
end
-- ftdetect/ of a folder added to the runtimepath after startup isn't read: register the file types here
vim.filetype.add({ extension = { game = "tabula", sheet = "tabula" } })
