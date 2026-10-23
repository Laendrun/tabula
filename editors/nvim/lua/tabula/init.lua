-- Tabula for Neovim: starts the language server `tabula lsp` for .game and .sheet files. The server (the same
-- parser as every tabula command) gives problems as you type, completion, hover (K), go to definition (gd),
-- references, rename, quick fixes, formatting, symbols, folding, links, inline hints and use counts. This
-- plugin adds :TabulaPreview (the page in your browser). The highlighting is in syntax/tabula.vim.
--
--   require("tabula").setup({ cmd = { "tabula" } })     -- optional: the defaults work
--
-- Needs Neovim 0.10+ and tabula with pygls (pipx install ./cli, then pipx inject tabula pygls).
local M = {}

M.config = {
  cmd = { "tabula" },          -- how to run tabula, e.g. { "python3", "-m", "tabula" }
  spell = false,               -- also check spelling (tabula check --spell)
  definitions = false,         -- every component needs a glossary definition
  autocomplete = true,         -- open the completion menu as you type [[, {=, :x… (Neovim 0.11+)
  format_on_save = false,      -- run tabula fmt (through the server) when saving
  keymaps = true,              -- gd: go to the definition (K is Neovim's hover already)
}

local warned = {}

local function warn_once(key, msg)
  if warned[key] then return end
  warned[key] = true
  vim.schedule(function() vim.notify(msg, vim.log.levels.WARN) end)
end

--- The vault's root for a file: the folder with vault.yaml, else the one with _shared/.
function M.vault_root(file)
  local dir = vim.fs.dirname(file)
  local found = vim.fs.find({ "vault.yaml", "vault.yml" }, { upward = true, path = dir })[1]
    or vim.fs.find({ "_shared" }, { upward = true, path = dir, type = "directory" })[1]
  return found and vim.fs.dirname(found) or dir
end

-- ------------------------------------------------------------------ the language server

--- "used N times" above definitions: the places, in the quickfix list.
local function show_references(command)
  local locations = (command.arguments or {})[3] or {}
  if #locations == 0 then return end
  local client = vim.lsp.get_clients({ name = "tabula" })[1]
  local items = vim.lsp.util.locations_to_items(locations, client and client.offset_encoding or "utf-16")
  vim.fn.setqflist({}, " ", { title = "Tabula: references", items = items })
  vim.cmd("copen")
end
M.show_references = show_references

--- Start (or reuse) the language server for a buffer. Returns the client id, or nil.
function M.start(buf)
  local c = M.config
  local file = vim.api.nvim_buf_get_name(buf)
  if vim.fn.executable(c.cmd[1]) == 0 then
    warn_once("missing", "tabula: can't run `" .. table.concat(c.cmd, " ") .. "`: install tabula (pipx install ./cli "
      .. "in the tabula repository, then pipx inject tabula pygls), or set `cmd` in require('tabula').setup()")
    return nil
  end
  vim.lsp.commands["tabula.showReferences"] = show_references
  local cmd = vim.list_extend(vim.deepcopy(c.cmd), { "lsp" })
  return vim.lsp.start({
    name = "tabula",
    cmd = cmd,
    root_dir = M.vault_root(file),
    init_options = { spell = c.spell, definitions = c.definitions, images = "none" },
    on_exit = function(code)
      if code == 2 then
        warn_once("pygls", "tabula: the language server needs pygls: pipx inject tabula pygls "
          .. "(or pip install 'tabula[lsp]'). See :LspLog")
      end
    end,
  }, { bufnr = buf })
end

-- ------------------------------------------------------------------ the preview (tabula export / sheet)

--- Export the buffer as an interactive page and open it in the browser (a .sheet: the printable sheet).
function M.preview(buf)
  buf = (buf == nil or buf == 0) and vim.api.nvim_get_current_buf() or buf
  local file = vim.api.nvim_buf_get_name(buf)
  local out = vim.fn.tempname() .. ".html"
  local args = vim.deepcopy(M.config.cmd)
  vim.list_extend(args, { "--vault", M.vault_root(file) })
  if file:match("%.sheet$") then
    vim.list_extend(args, { "sheet", file, "--stdin", "-o", out })
  else
    vim.list_extend(args, { "export", file, "--interactive", "--stdin", "-o", out })
  end
  local text = table.concat(vim.api.nvim_buf_get_lines(buf, 0, -1, false), "\n") .. "\n"
  local ok, err = pcall(vim.system, args, { stdin = text, text = true }, function(res)
    vim.schedule(function()
      if res.code ~= 0 then
        vim.notify("tabula: " .. vim.trim(res.stderr or ""), vim.log.levels.WARN)
      else
        vim.ui.open(out)
      end
    end)
  end)
  if not ok then vim.notify("tabula: " .. tostring(err), vim.log.levels.WARN) end
end

-- ------------------------------------------------------------------ buffer setup

--- Called by ftplugin/tabula.lua for every tabula buffer.
function M.attach(buf)
  local c = M.config
  vim.bo[buf].commentstring = "<!-- %s -->"
  local group = vim.api.nvim_create_augroup("tabula_buf_" .. buf, { clear = true })
  vim.api.nvim_buf_create_user_command(buf, "TabulaPreview", function() M.preview(buf) end,
    { desc = "Open the game (or the sheet) in the browser" })
  vim.api.nvim_buf_create_user_command(buf, "TabulaFormat", function()
    vim.lsp.buf.format({ bufnr = buf, name = "tabula" })
  end, { desc = "tabula fmt" })
  vim.api.nvim_buf_create_user_command(buf, "TabulaCheck", function()
    vim.diagnostic.setqflist({ title = "Tabula", open = true })
  end, { desc = "tabula's problems in the quickfix list" })
  vim.api.nvim_create_autocmd("LspAttach", { group = group, buffer = buf, callback = function(ev)
    local client = vim.lsp.get_client_by_id(ev.data.client_id)
    if not client or client.name ~= "tabula" then return end
    if c.keymaps then
      vim.keymap.set("n", "gd", vim.lsp.buf.definition, { buffer = buf, desc = "Tabula: go to the definition" })
    end
    if c.autocomplete and vim.lsp.completion and vim.lsp.completion.enable then
      vim.lsp.completion.enable(true, client.id, buf, { autotrigger = true })
    end
    if vim.lsp.inlay_hint and vim.lsp.inlay_hint.enable then
      pcall(vim.lsp.inlay_hint.enable, true, { bufnr = buf })
    end
  end })
  if c.format_on_save then
    vim.api.nvim_create_autocmd("BufWritePre", { group = group, buffer = buf, callback = function()
      if #vim.lsp.get_clients({ bufnr = buf, name = "tabula" }) > 0 then
        vim.lsp.buf.format({ bufnr = buf, name = "tabula", timeout_ms = 3000 })
      end
    end })
  end
  M.start(buf)
end

function M.setup(opts)
  M.config = vim.tbl_deep_extend("force", M.config, opts or {})
  warned = {}
end

return M
