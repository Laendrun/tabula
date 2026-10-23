-- Tests for the Neovim plugin. Run from the repository's root:
--   nvim --headless -u NONE -l editors/nvim/tests/test.lua
-- The language server is `tabula lsp` (TABULA_CMD="python3 -m tabula" to use another command; it needs pygls).
local root = vim.fn.fnamemodify(debug.getinfo(1, "S").source:sub(2), ":p:h:h:h:h")
vim.opt.rtp:prepend(root .. "/editors/nvim")
vim.opt.swapfile = false
vim.cmd("filetype plugin on")
vim.cmd("syntax on")

local tabula = require("tabula")
local cmd = vim.env.TABULA_CMD and vim.split(vim.env.TABULA_CMD, " ") or { "tabula" }
tabula.setup({ cmd = cmd, autocomplete = false })

local failures, count = 0, 0
local function test(name, f)
  count = count + 1
  local ok, err = pcall(f)
  if ok then
    print("ok   " .. name)
  else
    failures = failures + 1
    print("FAIL " .. name .. "\n     " .. tostring(err))
  end
end
local function eq(a, b, what)
  if not vim.deep_equal(a, b) then
    error((what and (what .. ": ") or "") .. "expected " .. vim.inspect(b) .. ", got " .. vim.inspect(a), 2)
  end
end

local tmp = vim.fn.tempname()
vim.fn.mkdir(tmp .. "/v/g", "p")
vim.fn.mkdir(tmp .. "/v/_shared", "p")
vim.fn.writefile({ "values:", "  target: 100", "symbols:", "  gold: media/gold.png" }, tmp .. "/v/vault.yaml")
vim.fn.writefile({ "# Glossaire {#glossary}", "", "Carte", ": Une carte à jouer." }, tmp .. "/v/_shared/deck.game")
local GAME = {
  "---",
  "title: G",
  "players: 2-4",
  "values:",
  "  main: {2p: 7, \"*\": 5}",
  "extensions:",
  "  pandora:",
  "    description: P",
  "    ",
  "---",
  "# Matériel {#components}",
  "",
  "- {+pandora} 3x [[Jeton|jetons]] :gold:",
  "- 2x [[Pion]]",
  "",
  "# Mise en place {#setup}",
  "",
  "! Distribuez {=main} cartes à chacun, {3p: une | *: deux} [[",
  "Voir [[#",
  "",
  "## ! Si la tour tombe",
  "",
  "> [!exemple] Un titre",
  "> Texte avec **gras**.",
  "",
  "# Glossaire {#glossary}",
  "",
  "![[deck#Glossaire]]",
  "",
  "Jeton",
  ": points:: 3",
  "  Un jeton rond.",
  "<!-- TODO: finir -->",
}
local file = tmp .. "/v/g/g.game"
vim.fn.writefile(GAME, file)
vim.cmd.edit(file)
local buf = vim.api.nvim_get_current_buf()

local function group_at(row, col)
  local id = vim.fn.synID(row, col, 1)
  return vim.fn.synIDattr(id, "name")
end

test("filetype", function()
  eq(vim.bo.filetype, "tabula")
  eq(vim.bo.commentstring, "<!-- %s -->")
end)

test("highlighting", function()
  eq(group_at(2, 1):match("^yaml") ~= nil, true, "frontmatter is YAML")
  eq(group_at(11, 1), "tabulaHeadingMark")
  eq(group_at(11, 15), "tabulaRole")
  eq(group_at(13, 4), "tabulaCond")
  eq(group_at(13, 14), "tabulaCount")
  eq(group_at(13, 22), "tabulaRef")
  eq(group_at(13, 36), "tabulaSymbol")
  eq(group_at(18, 1), "tabulaKeyRuleBang")
  eq(group_at(18, 15), "tabulaValue")
  eq(group_at(18, 41), "tabulaChoiceKey")
  eq(group_at(18, 51), "tabulaChoiceKey")
  eq(group_at(18, 45), "tabulaChoice")
  eq(group_at(21, 4), "tabulaKeyBang")
  eq(group_at(23, 3), "tabulaCallout")
  eq(group_at(24, 20), "tabulaBold")
  eq(group_at(28, 1), "tabulaInclude")
  eq(group_at(30, 1), "tabulaTerm")
  eq(group_at(31, 3), "tabulaField")
  eq(group_at(33, 6), "tabulaTodo")
end)

local function wait_for(f, ms)
  return vim.wait(ms or 20000, f, 50)
end

local function client()
  return vim.lsp.get_clients({ bufnr = buf, name = "tabula" })[1]
end

local function request(method, params)
  local res = vim.lsp.buf_request_sync(buf, method, params, 20000)
  for _, r in pairs(res or {}) do
    if r.err then error(vim.inspect(r.err)) end
    return r.result
  end
end

local function at(line, col)          -- 0-based line, byte column (converted to the server's encoding)
  local text = vim.api.nvim_buf_get_lines(buf, line, line + 1, false)[1] or ""
  local enc = client().offset_encoding
  local ok, c = pcall(vim.str_utfindex, text, enc, col, false)            -- Neovim 0.11
  if not ok or type(c) ~= "number" then
    local u32, u16 = vim.str_utfindex(text, col)                           -- Neovim 0.10
    c = enc == "utf-16" and u16 or enc == "utf-8" and col or u32
  end
  return { textDocument = { uri = vim.uri_from_bufnr(buf) }, position = { line = line, character = c } }
end

test("the language server starts", function()
  eq(wait_for(function() return client() ~= nil end), true, "attached")
  eq(client().config.cmd[#client().config.cmd], "lsp")
  eq(client().config.root_dir, tmp .. "/v")
end)

test("problems as you type (tabula check)", function()
  vim.api.nvim_buf_set_lines(buf, 18, 19, false, { "Voir [[Crad]]." })
  eq(wait_for(function()
    return #vim.tbl_filter(function(d) return d.message:find("Crad", 1, true) end, vim.diagnostic.get(buf)) > 0
  end), true, "the unknown reference is reported")
  local d = vim.tbl_filter(function(x) return x.message:find("Crad", 1, true) end, vim.diagnostic.get(buf))[1]
  eq({ d.lnum, d.col, d.end_col }, { 18, 5, 13 })
  local todo = vim.tbl_filter(function(x) return x.severity == vim.diagnostic.severity.INFO end, vim.diagnostic.get(buf))
  eq(#todo >= 1, true, "the TODO is information")
end)

test("completion: terms (the fragment's too), values, frontmatter keys", function()
  local r = request("textDocument/completion", at(17, #GAME[18]))
  local labels = vim.tbl_map(function(i) return i.label end, r.items or r)
  eq(labels, { "Jeton", "Carte", "Pion" })
  vim.api.nvim_buf_set_lines(buf, 19, 20, false, { "Prenez {=" })
  r = request("textDocument/completion", at(19, 9))
  eq(vim.tbl_map(function(i) return i.label end, r.items or r), { "main", "target" })
  r = request("textDocument/completion", at(8, 4))
  eq(vim.tbl_map(function(i) return i.label end, r.items or r), { "players", "duration", "year", "needs", "excludes" })
  vim.api.nvim_buf_set_lines(buf, 19, 20, false, { "" })
end)

test("hover, go to definition, references (after an emoji)", function()
  vim.api.nvim_buf_set_lines(buf, 19, 20, false, { "🎲 Prenez des [[jetons]]." })
  local col = ("🎲 Prenez des [["):len() + 2          -- bytes: the emoji is 4
  local h = request("textDocument/hover", at(19, col))
  eq(h.contents.value:sub(1, 9), "**Jeton**")
  local d = request("textDocument/definition", at(19, col))
  eq(d[1].range.start.line, 29)
  local refs = request("textDocument/references", vim.tbl_extend("force", at(19, col), { context = { includeDeclaration = false } }))
  eq(#refs, 2)
  vim.api.nvim_set_current_buf(buf)
  vim.api.nvim_win_set_cursor(0, { 13, 20 })
  vim.lsp.buf.definition()
  eq(wait_for(function() return vim.api.nvim_win_get_cursor(0)[1] == 30 end, 5000), true, "gd jumps to Jeton")
  vim.api.nvim_buf_set_lines(buf, 19, 20, false, { "" })
end)

test("rename, symbols, inlay hints, code lens", function()
  local edit = request("textDocument/rename", vim.tbl_extend("force", at(29, 1), { newName = "Pièce" }))
  local texts = vim.tbl_map(function(e) return e.newText end, edit.changes[vim.uri_from_bufnr(buf)])
  table.sort(texts)
  eq(texts, { "Pièce", "[[Pièce|jetons]]" })
  local syms = request("textDocument/documentSymbol", { textDocument = { uri = vim.uri_from_bufnr(buf) } })
  eq(vim.tbl_map(function(s) return s.name end, syms), { "Matériel", "Mise en place", "Glossaire" })
  local hints = request("textDocument/inlayHint", { textDocument = { uri = vim.uri_from_bufnr(buf) },
    range = { start = { line = 0, character = 0 }, ["end"] = { line = 40, character = 0 } } })
  eq(vim.tbl_map(function(x) return x.label end, hints), { "= 2p 7 · * 5" })
  local lenses = request("textDocument/codeLens", { textDocument = { uri = vim.uri_from_bufnr(buf) } })
  eq(lenses[1].command.title, "used once")
  vim.fn.setqflist({}, "r")
  tabula.show_references(lenses[1].command)
  eq(#vim.fn.getqflist(), 1)
  vim.cmd("cclose")
end)

test("formatting through the server", function()
  vim.api.nvim_buf_set_lines(buf, 19, 20, false, { "", "", "" })
  vim.lsp.buf.format({ bufnr = buf, name = "tabula", timeout_ms = 10000 })
  local lines = vim.api.nvim_buf_get_lines(buf, 0, -1, false)
  local at_ = vim.fn.index(lines, "Voir [[Crad]].") + 1
  eq(at_ > 0, true)
  eq({ lines[at_ + 1], lines[at_ + 2] }, { "", "## ! Si la tour tombe" }, "blank lines collapsed")
end)

test("without tabula: one message, no server", function()
  local messages = {}
  local notify = vim.notify
  vim.notify = function(m) messages[#messages + 1] = m end
  tabula.setup({ cmd = { "tabula-command-that-does-not-exist" } })
  eq(tabula.start(buf), nil)
  eq(tabula.start(buf), nil)
  vim.wait(50)
  vim.notify = notify
  eq(#messages, 1)
  eq(messages[1]:find("pipx inject tabula pygls", 1, true) ~= nil, true)
  tabula.setup({ cmd = cmd })
end)

print(string.format("\n%d tests, %d failed", count, failures))
vim.fn.delete(tmp, "rf")
os.exit(failures == 0 and 0 or 1)
