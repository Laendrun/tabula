-- Tabula buffers (.game, .sheet): completion, checks, K / gd, :TabulaCheck, :TabulaFormat, :TabulaPreview
if vim.b.did_ftplugin then return end
vim.b.did_ftplugin = 1

vim.opt_local.wrap = true
vim.opt_local.linebreak = true
vim.opt_local.comments = "fb:-,fb:*,fb:+,n:>"
vim.opt_local.formatoptions:remove("t")
vim.b.undo_ftplugin = "setlocal wrap< linebreak< comments< formatoptions< omnifunc< commentstring<"

require("tabula").attach(vim.api.nvim_get_current_buf())
