-- So that plugin managers find the module at the repository's root (lazy.nvim's `opts`, `require("tabula")`).
-- The plugin itself is in editors/nvim.
local root = vim.fn.fnamemodify(debug.getinfo(1, "S").source:sub(2), ":p:h:h:h")
return dofile(root .. "/editors/nvim/lua/tabula/init.lua")
