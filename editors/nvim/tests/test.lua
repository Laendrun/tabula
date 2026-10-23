-- Tests for the Neovim plugin. Run from the repository's root:
--   nvim --headless -u NONE -l editors/nvim/tests/test.lua
-- Checks and formatting run `tabula` (TABULA_CMD="python3 -m tabula" to use another command).
local root = vim.fn.fnamemodify(debug.getinfo(1, "S").source:sub(2), ":p:h:h:h:h")
vim.opt.rtp:prepend(root .. "/editors/nvim")
vim.opt.swapfile = false
vim.cmd("filetype plugin on")
vim.cmd("syntax on")

local tabula = require("tabula")
local cmd = vim.env.TABULA_CMD and vim.split(vim.env.TABULA_CMD, " ") or { "tabula" }
tabula.setup({ cmd = cmd, check_on_change = false, autocomplete = false })

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
  eq(vim.bo.omnifunc, "v:lua.require'tabula'.omnifunc")
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

-- a scratch buffer in the vault: its outline comes from `tabula outline --stdin`
local scratch = vim.api.nvim_create_buf(false, true)
local scratch_file = tmp .. "/v/g/scratch.game"
vim.api.nvim_buf_set_name(scratch, scratch_file)
local function outline_of(lines)
  vim.api.nvim_buf_set_lines(scratch, 0, -1, false, lines)
  return tabula.outline(scratch)
end
local function items(lines, row, col)
  local o = outline_of(lines)
  return (tabula.items(o, lines[row], row, col, scratch_file))
end
local function words(lines, row, col)
  return vim.tbl_map(function(i) return i.word end, items(lines, row, col) or {})
end

test("outline (from tabula outline --json)", function()
  local o = outline_of(GAME)
  eq({ o.frontmatter.start, o.frontmatter["end"] }, { 1, 8 })
  eq(vim.tbl_map(function(c) return c.name end, o.components), { "Jeton", "Pion" })
  eq(o.definitions[1].term, "Jeton")
  eq(o.definitions[1].markdown, "**points:** 3\n\nUn jeton rond.")
  eq(o.includes[1].name, "deck")
  eq(o.headings[3].key, true)
  eq(o.fragments[1].definitions[1].term, "Carte")
  eq(tabula.outline(scratch) == o, true, "kept until the buffer changes")
end)

test("completes terms (and the fragment's), sections, values, symbols", function()
  eq(words(GAME, 18, #GAME[18]), { "Jeton]]", "Carte]]", "Pion]]" })
  local sec = words(GAME, 19, #GAME[19])
  eq(sec[1], "Matériel]]")
  eq(vim.tbl_contains(sec, "setup]]"), true)
  local g = vim.list_extend(vim.deepcopy(GAME), { "Prenez {=" })
  eq(words(g, #g, #g[#g]), { "main}", "target}" })
  g[#g] = "Payez 3 :go"
  eq(words(g, #g, #g[#g]), { ":gold:" })
  g[#g] = "À 10:30 heures"
  eq(items(g, #g, 6), nil)
  g[#g] = "![[de"
  eq(words(g, #g, #g[#g]), { "deck]]" })
  g[#g] = "![[deck#Gl"
  eq(words(g, #g, #g[#g]), { "Glossaire]]", "glossary]]" })          -- its title and its role
end)

test("completes frontmatter keys and extension details", function()
  local g = vim.deepcopy(GAME)
  g[4] = "pla"
  local keys = vim.tbl_map(function(i) return i.abbr end, items(g, 4, 3))
  eq(vim.tbl_contains(keys, "players"), false, "already there")
  g[3] = "x: 1"
  keys = vim.tbl_map(function(i) return i.abbr end, items(g, 4, 3))
  eq(vim.tbl_contains(keys, "players"), true)
  keys = vim.tbl_map(function(i) return i.abbr end, items(GAME, 9, 4))
  eq(keys, { "duration", "excludes", "needs", "players", "year" })
end)

test("go to definition and hover", function()
  vim.api.nvim_set_current_buf(buf)
  vim.api.nvim_win_set_cursor(0, { 13, 20 })
  tabula.goto_definition()
  eq(vim.api.nvim_win_get_cursor(0), { 30, 0 })
  local o = tabula.outline(buf)
  local carte = vim.tbl_filter(function(r) return r.name == "Pion" end, o.references)[1]
  eq(tabula.find_target(o, carte).line, 13)                          -- 0-based: the component line
  local line = "Voir [[#setup]] et 🎲 [[jetons]]."
  local o2 = outline_of(vim.list_extend(vim.deepcopy(GAME), { line }))
  local row = #GAME + 1
  local setup = tabula.ref_at(o2, line, row, 8)
  eq(setup.name, "setup")
  eq(tabula.find_target(o2, setup).line, 15)
  local jetons = tabula.ref_at(o2, line, row, line:find("jetons", 1, true))      -- after an emoji: bytes vs characters
  eq(jetons.name, "jetons")
  eq(tabula.hover_lines(o2, jetons)[1], "**Jeton**")
  eq(tabula.byte_col(line, jetons.start), line:find("[[jetons", 1, true) - 1)
end)

test("issue columns", function()
  eq({ tabula.issue_columns("Voir [[crad]] ici", "reference [[crad]] matches nothing") }, { 5, 13 })
  eq({ tabula.issue_columns("  Texte", "something") }, { 2, 7 })
end)

local function wait_for(f)
  return vim.wait(15000, f, 50)
end

test("check: tabula's problems as diagnostics", function()
  vim.api.nvim_buf_set_lines(buf, 18, 19, false, { "Voir [[Crad]]." })
  tabula.check(buf)
  eq(wait_for(function() return #vim.diagnostic.get(buf) > 0 end), true, "diagnostics arrived")
  local d = vim.tbl_filter(function(x) return x.message:find("Crad", 1, true) end, vim.diagnostic.get(buf))[1]
  eq(d ~= nil, true, "the unknown reference is reported")
  eq({ d.lnum, d.col, d.end_col }, { 18, 5, 13 })
  local todo = vim.tbl_filter(function(x) return x.severity == vim.diagnostic.severity.INFO end, vim.diagnostic.get(buf))
  eq(#todo >= 1, true, "the TODO is information")
end)

test("format", function()
  vim.api.nvim_buf_set_lines(buf, 19, 20, false, { "", "", "" })
  local done
  tabula.format(buf, function(ok) done = ok end)
  eq(wait_for(function() return done ~= nil end), true)
  eq(done, true)
  local lines = vim.api.nvim_buf_get_lines(buf, 0, -1, false)
  local at = vim.fn.index(lines, "Voir [[Crad]].") + 1
  eq(at > 0, true)
  eq({ lines[at + 1], lines[at + 2] }, { "", "## ! Si la tour tombe" }, "blank lines collapsed")
end)

test("without tabula: formatting doesn't wait", function()
  tabula.setup({ cmd = { "tabula-command-that-does-not-exist" } })
  local notify = vim.notify
  vim.notify = function() end
  local done, t0 = nil, vim.uv.hrtime()
  tabula.format(buf, function(ok) done = ok end)
  tabula.format(buf, function(ok) done = ok end)          -- the second time too (tabula known to be missing)
  vim.notify = notify
  eq(done, false)
  eq((vim.uv.hrtime() - t0) / 1e6 < 500, true, "no wait")
  tabula.setup({ cmd = cmd })
end)

print(string.format("\n%d tests, %d failed", count, failures))
vim.fn.delete(tmp, "rf")
os.exit(failures == 0 and 0 or 1)
