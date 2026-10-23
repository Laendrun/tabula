-- Tabula for Neovim: completion, checks (diagnostics), hover, go to definition, formatting and preview
-- for .game and .sheet files. The syntax highlighting is in syntax/tabula.vim.
--
--   require("tabula").setup({ cmd = { "tabula" } })     -- optional: the defaults work
--
-- Needs Neovim 0.10+, and the `tabula` CLI for checks, formatting and preview.
local M = {}

M.config = {
  cmd = { "tabula" },          -- how to run tabula, e.g. { "python3", "-m", "tabula" }
  check = true,                -- run `tabula check` and show its problems as diagnostics
  check_on_change = true,      -- also while typing (after a pause), not only when saving
  debounce = 600,              -- ms of pause before checking while typing
  spell = false,               -- also `--spell` (needs tabula with spylls)
  autocomplete = true,         -- open the completion menu after [[, [[#, ![[, {= and :x
  format_on_save = false,      -- run `tabula fmt` when saving
  keymaps = true,              -- K: hover, gd: go to definition (in tabula buffers)
}

local ns = vim.api.nvim_create_namespace("tabula")

-- ------------------------------------------------------------------ helpers

local function read_lines(path)
  local f = io.open(path, "r")
  if not f then return nil end
  local text = f:read("*a")
  f:close()
  return vim.split(text:gsub("\r\n", "\n"), "\n", { plain = true })
end

--- The vault's root: the nearest folder above the file with a vault.yaml (or nil).
function M.vault_root(file)
  local found = vim.fs.find({ "vault.yaml", "vault.yml" }, { upward = true, path = vim.fs.dirname(file) })[1]
  return found and vim.fs.dirname(found) or nil
end

--- A column of the outline (characters) as a byte column on that line, and back.
local function byte_col(line, cp)
  local ok, r = pcall(vim.str_byteindex, line, "utf-32", cp, false)          -- Neovim 0.11
  if ok and type(r) == "number" then return r end
  ok, r = pcall(vim.str_byteindex, line, cp)                                  -- Neovim 0.10
  return ok and r or #line
end
local function char_col(line, byte)
  return vim.fn.strchars(line:sub(1, byte))
end
M.byte_col, M.char_col = byte_col, char_col

-- ------------------------------------------------------------------ the outline: tabula reads the file

-- The plugin doesn't parse .game files: `tabula outline --json` does, with the same parser as every other
-- tabula command. Its result is kept until the buffer changes.

local missing = false        -- the tabula command isn't there: said once, then everything that needs it is off

local function say_missing(err)
  missing = true
  vim.schedule(function()
    vim.notify("tabula: can't run `" .. table.concat(M.config.cmd, " ") .. "`: install tabula (pipx install ./cli in "
      .. "the tabula repository), or set `cmd` in require('tabula').setup(). Completion, K, gd, checks and "
      .. "formatting need it (" .. tostring(err):gsub("^.-: ", "") .. ")", vim.log.levels.WARN)
  end)
end

local function outline_args(file, stdin)
  local args = {}
  local root = M.vault_root(file)
  if root then vim.list_extend(args, { "--vault", root }) end
  vim.list_extend(args, { "outline", file, "--json" })
  if stdin then args[#args + 1] = "--stdin" end
  return args
end

local function run_outline(file, input)
  if missing then return nil end
  local cmd = vim.list_extend(vim.deepcopy(M.config.cmd), outline_args(file, input ~= nil))
  local ok, proc = pcall(vim.system, cmd, { stdin = input, text = true })
  if not ok then
    say_missing(proc)
    return nil
  end
  local res = proc:wait(10000)
  if res.code ~= 0 then return nil end
  local okj, data = pcall(vim.json.decode, res.stdout or "", { luanil = { object = true, array = true } })
  if not okj or type(data) ~= "table" or data.outline ~= 1 then return nil end
  return data
end

local cache = {}             -- buffer -> { tick, data }
local file_cache = {}        -- path -> { mtime, data }

--- The outline of a buffer as it is now (unsaved changes included), or nil when tabula can't read it.
function M.outline(buf)
  buf = (buf == nil or buf == 0) and vim.api.nvim_get_current_buf() or buf
  local tick = vim.api.nvim_buf_get_changedtick(buf)
  local c = cache[buf]
  if c and c.tick == tick then return c.data end
  local text = table.concat(vim.api.nvim_buf_get_lines(buf, 0, -1, false), "\n") .. "\n"
  local data = run_outline(vim.api.nvim_buf_get_name(buf), text)
  cache[buf] = { tick = tick, data = data }
  return data
end

--- The outline of a file on disk (a shared fragment), kept until the file changes.
function M.outline_file(path)
  local st = vim.uv.fs_stat(path)
  if not st then return nil end
  local c = file_cache[path]
  if c and c.mtime == st.mtime.sec .. "." .. st.mtime.nsec then return c.data end
  local data = run_outline(path, nil)
  file_cache[path] = { mtime = st.mtime.sec .. "." .. st.mtime.nsec, data = data }
  return data
end

--- Every definition (or component) the file can refer to: its own, the fragments', the default-language file's.
local function all_of(o, kind)
  local out = {}
  for _, x in ipairs(o[kind]) do out[#out + 1] = vim.tbl_extend("force", x, { file = false }) end
  for _, f in ipairs(o.fragments or {}) do
    for _, x in ipairs(f[kind]) do out[#out + 1] = vim.tbl_extend("force", x, { file = f.file, from = f.name }) end
  end
  if o.default then
    for _, x in ipairs(o.default[kind]) do out[#out + 1] = vim.tbl_extend("force", x, { file = o.default.file }) end
  end
  return out
end

-- ------------------------------------------------------------------ completion

local SCHEMAS
local function schemas()
  if SCHEMAS ~= nil then return SCHEMAS end
  SCHEMAS = false
  -- this file is editors/nvim/lua/tabula/init.lua in the tabula repository; the schemas are in spec/schemas
  local here = debug.getinfo(1, "S").source:sub(2)
  local root = vim.fs.dirname(vim.fs.dirname(vim.fs.dirname(vim.fs.dirname(vim.fs.dirname(here)))))
  local out = {}
  for _, name in ipairs({ "game", "sheet" }) do
    local lines = read_lines(root .. "/spec/schemas/" .. name .. ".schema.json")
    if lines then
      local ok, data = pcall(vim.json.decode, table.concat(lines, "\n"))
      if ok then out[name] = data end
    end
  end
  if next(out) then SCHEMAS = out end
  return SCHEMAS
end

local function schema_keys(kind, level)
  local s = schemas()
  local root = s and s[kind]
  if not root then return {} end
  local props = root.properties or {}
  if level == "option" then
    local opt = ((props.extensions or {}).oneOf or {})[2]
    opt = opt and opt.additionalProperties or {}
    props = {}
    for _, o in ipairs(opt.oneOf or {}) do
      if o.type == "object" then props = o.properties or {} end
    end
  end
  local keys = {}
  for k, v in pairs(props) do keys[#keys + 1] = { key = k, description = v.description or "" } end
  table.sort(keys, function(a, b) return a.key < b.key end)
  return keys
end

--- The frontmatter key being typed: { level, start, present } or nil. `row0`: the 0-based line.
local function frontmatter_context(o, before, row0)
  local fm = o.frontmatter
  if not fm or row0 < fm.start or row0 > fm["end"] then return nil end
  local ind = before:match("^(%s*)[%w_-]*$")
  if not ind then return nil end
  local present = {}
  if #ind == 0 then
    for _, k in ipairs(fm.keys) do
      if k.level == "top" and k.line ~= row0 then present[k.key] = true end
    end
    return { level = "top", start = 0, present = present }
  end
  local opt
  for _, x in ipairs(fm.options) do
    if x.line < row0 and #ind > x.indent then opt = x end
  end
  if not opt then return nil end
  for _, k in ipairs(fm.keys) do
    if k.level == "top" and k.line > opt.line and k.line <= row0 then return nil end
    if k.option == opt.name and k.line ~= row0 then present[k.key] = true end
  end
  return { level = "option", start = #ind, present = present }
end

--- What is being completed at the cursor: { kind, start (0-based byte column), typed } or nil.
--- kind: "term", "section", "fragment", "fragment-section", "value", "symbol" or "key" (frontmatter).
function M.context(o, line, row, col)
  local before = (line or ""):sub(1, col)
  if o and o.frontmatter and row - 1 >= o.frontmatter.start and row - 1 <= o.frontmatter["end"] then
    local fm = frontmatter_context(o, before, row - 1)
    if fm then return { kind = "key", level = fm.level, present = fm.present, start = fm.start, typed = before:sub(fm.start + 1) } end
    return nil
  end
  local s, name, typed = before:match("^%s*()!%[%[([^%]#|]*)#([^%]|]*)$")
  if s then return { kind = "fragment-section", name = vim.trim(name), start = #before - #typed, typed = typed } end
  s, typed = before:match("()!%[%[([^%]#|]*)$")
  if s then return { kind = "fragment", start = s + 2, typed = typed } end
  s, typed = before:match("()%[%[#([^%]|]*)$")
  if s then return { kind = "section", start = s + 2, typed = typed } end
  s, typed = before:match("()%[%[([^%]|#]*)$")
  if s then return { kind = "term", start = s + 1, typed = typed } end
  s, typed = before:match("(){=%s*([%w_-]*)$")
  if s then return { kind = "value", start = s + 1, typed = typed } end
  s, typed = before:match("():(%a[%w_+-]*)$")
  if s and (s == 1 or not before:sub(s - 1, s - 1):match("[%w_:\\/]")) then
    return { kind = "symbol", start = s - 1, typed = typed }
  end
  return nil
end

local function starts(word, typed)
  return typed == "" or vim.startswith(word:lower(), typed:lower())
end

--- What the typed text is compared with: the name (a symbol's without its colons).
function M.filter_text(item)
  return (type(item.user_data) == "table" and item.user_data.filter) or item.abbr or item.word
end

local function section_items(headings, close, add)
  for _, h in ipairs(headings) do
    if h.title ~= "" then add({ word = h.title .. close, abbr = h.title, kind = "s", menu = "section" }, "s|" .. h.fold) end
  end
  for _, h in ipairs(headings) do
    for _, r in ipairs(h.roles) do
      add({ word = r .. close, abbr = r, kind = "r", menu = "role → " .. h.title }, "r|" .. r)
    end
  end
end

--- Completion items at the cursor (complete-items): { word, abbr, menu, info, kind }, and the context.
function M.items(o, line, row, col, file)
  local ctx = M.context(o, line, row, col)
  if not ctx then return nil, nil end
  local out, seen = {}, {}
  local function add(item, key)
    if seen[key] or not starts(M.filter_text(item), ctx.typed) then return end
    seen[key] = true
    out[#out + 1] = item
  end
  local rest = (line or ""):sub(col + 1)
  local close = rest:match("^[^%]%[]*%]%]") and "" or "]]"
  if ctx.kind == "fragment" then
    local root = file and M.vault_root(file)
    for _, path in ipairs(root and vim.fn.glob(root .. "/_shared/*.game", false, true) or {}) do
      local name = vim.fn.fnamemodify(path, ":t:r")
      if not name:find("%.") then add({ word = name .. close, abbr = name, kind = "f", menu = "fragment" }, name) end
    end
    return out, ctx
  end
  if ctx.kind == "fragment-section" then
    local root = file and M.vault_root(file)
    local f = root and root .. "/_shared/" .. ctx.name .. ".game"
    local fo = f and M.outline_file(f)
    if fo then section_items(fo.headings, close, add) end
    return out, ctx
  end
  if not o then return nil, nil end
  if ctx.kind == "term" then
    for _, d in ipairs(all_of(o, "definitions")) do
      add({ word = d.term .. close, abbr = d.term, kind = "d", menu = d.from and ("def · " .. d.from) or "definition",
            info = d.markdown }, d.fold)
    end
    for _, c in ipairs(all_of(o, "components")) do
      add({ word = c.name .. close, abbr = c.name, kind = "c", menu = "component", info = c.text }, c.fold)
    end
  elseif ctx.kind == "section" then
    section_items(o.headings, close, add)
  elseif ctx.kind == "value" then
    local vclose = rest:match("^%s*}") and "" or "}"
    for _, v in ipairs(o.values) do
      add({ word = v.name .. vclose, abbr = v.name, kind = "v", menu = v.value, info = "value from " .. v.from }, v.name)
    end
  elseif ctx.kind == "symbol" then
    for _, v in ipairs(o.symbols) do
      add({ word = ":" .. v.name .. ":", abbr = ":" .. v.name .. ":", kind = "y", menu = v.text or v.src,
            info = "symbol from " .. v.from, user_data = { filter = v.name } }, v.name)
    end
  elseif ctx.kind == "key" then
    local kind = file and file:match("%.sheet$") and "sheet" or "game"
    for _, k in ipairs(schema_keys(kind, ctx.level)) do
      if not ctx.present[k.key] then
        add({ word = k.key .. ": ", abbr = k.key, kind = "k",
              menu = ctx.level == "option" and "detail" or "frontmatter", info = k.description }, k.key)
      end
    end
  end
  return out, ctx
end

--- 'omnifunc' for tabula buffers (also used by the automatic completion).
local pending = {}

function M.omnifunc(findstart, base)
  if findstart == 1 then
    local row, col = unpack(vim.api.nvim_win_get_cursor(0))
    local line = vim.api.nvim_get_current_line()
    local ctx = M.context(nil, line, row, col)
    -- the outline is needed for everything but fragment names (it's read again when the text changed)
    local o = (ctx and (ctx.kind == "fragment" or ctx.kind == "fragment-section")) and nil or M.outline(0)
    local items
    items, ctx = M.items(o, line, row, col, vim.api.nvim_buf_get_name(0))
    pending = items or {}
    return ctx and ctx.start or -3
  end
  -- Vim takes the typed text out of the line before this second call: filter by `base` instead
  local typed = base:gsub("^!?%[%[#?", ""):gsub("^{=%s*", ""):gsub("^:", "")
  return vim.tbl_filter(function(i) return starts(M.filter_text(i), typed) end, pending)
end

-- ------------------------------------------------------------------ hover and go to definition

--- The reference (from the outline) under a 1-based row and a byte column, or nil.
function M.ref_at(o, line, row, col)
  local c = char_col(line, col)
  for _, r in ipairs(o.references) do
    if r.line == row - 1 and c >= r.start and c < r["end"] then return r end
  end
  return nil
end

local function include_at(o, row)
  for _, i in ipairs(o.includes) do
    if i.line == row - 1 then return i end
  end
  return nil
end

--- Where a reference points to: { file (false: this buffer), line (0-based), item } or nil.
function M.find_target(o, ref)
  if ref.section then
    for _, h in ipairs(o.headings) do
      if h.fold == ref.fold then return { file = false, line = h.line, heading = h } end
    end
    for _, h in ipairs(o.headings) do
      for _, r in ipairs(h.roles) do
        if r == ref.name:lower() then return { file = false, line = h.line, heading = h } end
      end
    end
    return nil
  end
  for _, d in ipairs(all_of(o, "definitions")) do
    if d.fold == ref.fold then return { file = d.file, line = d.line, def = d } end
  end
  for _, c in ipairs(all_of(o, "components")) do
    if c.fold == ref.fold then return { file = c.file, line = c.line, component = c } end
  end
  return nil
end

local function hover_lines(o, ref)
  if ref.section then
    local t = M.find_target(o, ref)
    if not t then return nil end
    local h = t.heading
    return vim.split(("**%s%s**%s\n\n%s"):format(h.key and "★ " or "", h.title, h.cond ~= "" and (" `{" .. h.cond .. "}`") or "",
      h.preview), "\n")
  end
  local parts = {}
  for _, d in ipairs(all_of(o, "definitions")) do
    if d.fold == ref.fold then
      local pic = d.image and ("*picture: " .. d.image.src .. "*") or nil
      parts[#parts + 1] = table.concat(vim.tbl_filter(function(x) return x and x ~= "" end,
        { "**" .. d.term .. "**" .. (d.cond ~= "" and (" `{" .. d.cond .. "}`") or ""), pic, d.markdown }), "\n\n")
    end
  end
  local comps = {}
  for _, c in ipairs(o.components) do
    if c.fold == ref.fold then comps[#comps + 1] = "- " .. c.text end
  end
  if #comps > 0 then parts[#parts + 1] = table.concat(comps, "\n") end
  if #parts == 0 then return nil end
  return vim.split(table.concat(parts, "\n\n---\n\n"), "\n")
end
M.hover_lines = hover_lines

--- K: the definition of the reference under the cursor (or what an include brings) in a floating window.
function M.hover()
  local row, col = unpack(vim.api.nvim_win_get_cursor(0))
  local line = vim.api.nvim_get_current_line()
  local o = M.outline(0)
  local body
  if o then
    local inc = include_at(o, row)
    if inc then
      body = vim.split(inc.file and (("*from `_shared/%s`*\n\n%s"):format(inc.name, inc.preview or ""))
        or ("No shared fragment `" .. inc.name .. "`"), "\n")
    else
      local ref = M.ref_at(o, line, row, col)
      body = ref and hover_lines(o, ref)
    end
  end
  if not body then
    vim.cmd("normal! K")
    return
  end
  vim.lsp.util.open_floating_preview(body, "markdown", { border = "rounded", focus_id = "tabula-hover" })
end

--- gd: go to the definition, component line or heading of the reference under the cursor (or the fragment).
function M.goto_definition()
  local row, col = unpack(vim.api.nvim_win_get_cursor(0))
  local line = vim.api.nvim_get_current_line()
  local o = M.outline(0)
  local t
  if o then
    local inc = include_at(o, row)
    if inc and inc.file then
      t = { file = inc.file, line = inc.section_line or 0 }
    else
      local ref = M.ref_at(o, line, row, col)
      t = ref and M.find_target(o, ref)
    end
  end
  if not t then
    vim.cmd("normal! gd")
    return
  end
  vim.cmd("normal! m'")
  if t.file then vim.cmd.edit(vim.fn.fnameescape(t.file)) end
  vim.api.nvim_win_set_cursor(0, { t.line + 1, 0 })
end

-- ------------------------------------------------------------------ running tabula

--- Runs tabula; returns false (and never calls on_done) when it can't be run.
local function run(args, input, on_done)
  if missing then return false end
  local cmd = vim.list_extend(vim.deepcopy(M.config.cmd), args)
  local ok, err = pcall(vim.system, cmd, { stdin = input, text = true }, function(res)
    vim.schedule(function() on_done(res) end)
  end)
  if not ok then
    say_missing(err)
    return false
  end
  return true
end

local function buffer_text(buf)
  return table.concat(vim.api.nvim_buf_get_lines(buf, 0, -1, false), "\n") .. "\n"
end

--- Where to underline: the first thing the message quotes that is on the line, else the whole line.
function M.issue_columns(line, msg)
  local candidates = {}
  local w = msg:match("^unknown word '(.-)'")
  if w then candidates[#candidates + 1] = w end
  for c in msg:gmatch("(%[%[[^%]]*%]%]?)") do candidates[#candidates + 1] = c end
  for c in msg:gmatch("({[^{}]*})") do candidates[#candidates + 1] = c end
  for c in msg:gmatch("'([^']+)'") do candidates[#candidates + 1] = c end
  for c in msg:gmatch('"([^"]+)"') do candidates[#candidates + 1] = c end
  for _, c in ipairs(candidates) do
    local at = line:find(c, 1, true) or line:lower():find(c:lower(), 1, true)
    if at then return at - 1, at - 1 + #c end
  end
  local first = line:find("%S")
  return first and first - 1 or 0, #(line:gsub("%s+$", ""))
end

local SEVERITY = { error = vim.diagnostic.severity.ERROR, warning = vim.diagnostic.severity.WARN,
                   todo = vim.diagnostic.severity.INFO, spelling = vim.diagnostic.severity.HINT }

--- Run `tabula check` on a buffer (its unsaved text) and show the problems as diagnostics.
function M.check(buf)
  buf = (buf == nil or buf == 0) and vim.api.nvim_get_current_buf() or buf
  local file = vim.api.nvim_buf_get_name(buf)
  if file == "" then return end
  local args = {}
  local root = M.vault_root(file)
  if root then vim.list_extend(args, { "--vault", root }) end
  vim.list_extend(args, { "check", file, "--json", "--stdin" })
  if M.config.spell then args[#args + 1] = "--spell" end
  local tick = vim.api.nvim_buf_get_changedtick(buf)
  run(args, buffer_text(buf), function(res)
    if not vim.api.nvim_buf_is_valid(buf) or vim.api.nvim_buf_get_changedtick(buf) ~= tick then return end
    local out = res.stdout or ""
    local start = out:find("{", 1, true)
    local ok, data = pcall(vim.json.decode, start and out:sub(start) or "")
    if not ok or type(data) ~= "table" or type(data.issues) ~= "table" then
      if (res.stderr or "") ~= "" then
        vim.notify("tabula check: " .. vim.trim(res.stderr), vim.log.levels.WARN)
      end
      return
    end
    local by_buf = {}
    for _, f in ipairs(data.files or {}) do
      local b = vim.fn.bufnr(f)
      if b > 0 then by_buf[b] = by_buf[b] or {} end
    end
    by_buf[buf] = by_buf[buf] or {}
    for _, i in ipairs(data.issues) do
      local b = i.path == file and buf or vim.fn.bufnr(i.path)
      if b > 0 and by_buf[b] then
        local lnum = math.max((i.line or 1) - 1, 0)
        local text = (vim.api.nvim_buf_get_lines(b, lnum, lnum + 1, false)[1]) or ""
        local s, e = M.issue_columns(text, i.message or "")
        table.insert(by_buf[b], { lnum = lnum, col = s, end_col = e, message = i.message,
                                  severity = SEVERITY[i.level] or vim.diagnostic.severity.WARN, source = "tabula" })
      end
    end
    for b, list in pairs(by_buf) do vim.diagnostic.set(ns, b, list) end
  end)
end

--- Format a buffer with `tabula fmt` (keeps the cursor; does nothing when there is nothing to change).
function M.format(buf, done)
  buf = (buf == nil or buf == 0) and vim.api.nvim_get_current_buf() or buf
  local file = vim.api.nvim_buf_get_name(buf)
  local args = {}
  local root = M.vault_root(file)
  if root then vim.list_extend(args, { "--vault", root }) end
  vim.list_extend(args, { "fmt", file, "--stdin" })
  local tick = vim.api.nvim_buf_get_changedtick(buf)
  local started = run(args, buffer_text(buf), function(res)
    if res.code ~= 0 or not vim.api.nvim_buf_is_valid(buf) or vim.api.nvim_buf_get_changedtick(buf) ~= tick then
      if res.code ~= 0 then vim.notify("tabula fmt: " .. vim.trim(res.stderr or ""), vim.log.levels.WARN) end
      if done then done(false) end
      return
    end
    local new = vim.split((res.stdout or ""):gsub("\r\n", "\n"):gsub("\n$", ""), "\n", { plain = true })
    local old = vim.api.nvim_buf_get_lines(buf, 0, -1, false)
    if not vim.deep_equal(new, old) then
      local views = {}
      for _, w in ipairs(vim.fn.win_findbuf(buf)) do views[w] = vim.api.nvim_win_call(w, vim.fn.winsaveview) end
      vim.api.nvim_buf_set_lines(buf, 0, -1, false, new)
      for w, v in pairs(views) do vim.api.nvim_win_call(w, function() vim.fn.winrestview(v) end) end
    end
    if done then done(true) end
  end)
  if not started and done then done(false) end      -- no tabula: saving doesn't wait for it
end

--- Export the buffer as an interactive page and open it in the browser (a .sheet: the printable sheet).
function M.preview(buf)
  buf = (buf == nil or buf == 0) and vim.api.nvim_get_current_buf() or buf
  local file = vim.api.nvim_buf_get_name(buf)
  local out = vim.fn.tempname() .. ".html"
  local args = {}
  local root = M.vault_root(file)
  if root then vim.list_extend(args, { "--vault", root }) end
  if file:match("%.sheet$") then
    vim.list_extend(args, { "sheet", file, "--stdin", "-o", out })
  else
    vim.list_extend(args, { "export", file, "--interactive", "--stdin", "-o", out })
  end
  run(args, buffer_text(buf), function(res)
    if res.code ~= 0 then
      vim.notify("tabula: " .. vim.trim(res.stderr or ""), vim.log.levels.WARN)
      return
    end
    vim.ui.open(out)
  end)
end

-- ------------------------------------------------------------------ buffer setup

local timers = {}

--- Called by ftplugin/tabula.lua for every tabula buffer.
function M.attach(buf)
  local c = M.config
  vim.bo[buf].omnifunc = "v:lua.require'tabula'.omnifunc"
  vim.bo[buf].commentstring = "<!-- %s -->"
  local group = vim.api.nvim_create_augroup("tabula_buf_" .. buf, { clear = true })
  if c.keymaps then
    vim.keymap.set("n", "K", M.hover, { buffer = buf, desc = "Tabula: definition of the reference" })
    vim.keymap.set("n", "gd", M.goto_definition, { buffer = buf, desc = "Tabula: go to the definition" })
  end
  vim.api.nvim_buf_create_user_command(buf, "TabulaCheck", function() M.check(buf) end, { desc = "tabula check" })
  vim.api.nvim_buf_create_user_command(buf, "TabulaFormat", function() M.format(buf) end, { desc = "tabula fmt" })
  vim.api.nvim_buf_create_user_command(buf, "TabulaPreview", function() M.preview(buf) end,
    { desc = "Open the game (or the sheet) in the browser" })
  if c.check then
    vim.api.nvim_create_autocmd({ "BufWritePost", "BufEnter" }, { group = group, buffer = buf, callback = function() M.check(buf) end })
    if c.check_on_change then
      vim.api.nvim_create_autocmd({ "TextChanged", "InsertLeave" }, { group = group, buffer = buf, callback = function()
        if timers[buf] then timers[buf]:stop() end
        timers[buf] = vim.defer_fn(function() timers[buf] = nil; if vim.api.nvim_buf_is_valid(buf) then M.check(buf) end end, c.debounce)
      end })
    end
    M.check(buf)
  end
  if c.format_on_save then
    vim.api.nvim_create_autocmd("BufWritePre", { group = group, buffer = buf, callback = function()
      local done = false
      M.format(buf, function() done = true end)
      vim.wait(3000, function() return done end, 20)
    end })
  end
  if c.autocomplete then
    vim.api.nvim_create_autocmd("TextChangedI", { group = group, buffer = buf, callback = function()
      if vim.fn.pumvisible() == 1 then return end
      local row, col = unpack(vim.api.nvim_win_get_cursor(0))
      local before = vim.api.nvim_get_current_line():sub(1, col)
      local frontmatter = false
      if before:match("^%s*[%w_]$") then           -- the first letter of a frontmatter key
        local above = vim.api.nvim_buf_get_lines(buf, 0, row - 1, false)     -- still inside the frontmatter?
        frontmatter = row > 1 and above[1] == "---"
        for k = 2, #above do
          if above[k]:match("^%-%-%-%s*$") or above[k]:match("^%.%.%.%s*$") then frontmatter = false end
        end
      end
      if before:match("%[%[$") or before:match("%[%[#$") or before:match("{=$") or frontmatter
          or before:match("^:%a$") or before:match("[^%w_:\\/]:%a$") then
        vim.api.nvim_feedkeys(vim.keycode("<C-x><C-o>"), "n", false)
      end
    end })
  end
end

function M.setup(opts)
  M.config = vim.tbl_deep_extend("force", M.config, opts or {})
  missing = false
  cache, file_cache = {}, {}
end

return M
