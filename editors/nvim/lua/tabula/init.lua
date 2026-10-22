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

local function fold(s)
  -- the same key as tabula's references: case and accents ignored, a final s/x dropped
  s = vim.fn.tolower(s or "")
  local map = { ["à"] = "a", ["â"] = "a", ["ä"] = "a", ["á"] = "a", ["ç"] = "c", ["é"] = "e", ["è"] = "e",
                ["ê"] = "e", ["ë"] = "e", ["î"] = "i", ["ï"] = "i", ["í"] = "i", ["ô"] = "o", ["ö"] = "o",
                ["ó"] = "o", ["ù"] = "u", ["û"] = "u", ["ü"] = "u", ["ú"] = "u", ["ÿ"] = "y", ["ñ"] = "n",
                ["œ"] = "oe", ["æ"] = "ae", ["ß"] = "ss", ["’"] = "'" }
  for k, v in pairs(map) do s = s:gsub(k, v) end
  s = s:gsub("[%.,;:!%?%(%)%[%]{}\"/]", " ")
  local words = {}
  for w in s:gmatch("%S+") do
    if vim.fn.strchars(w) > 3 and w:match("[sx]$") and not w:match("ss$") then w = w:sub(1, -2) end
    words[#words + 1] = w
  end
  return table.concat(words, " ")
end
M.fold = fold

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

-- ------------------------------------------------------------------ reading a game

--- Headings, definitions (with their body), components, includes and the frontmatter range of a game.
function M.outline(lines)
  local o = { headings = {}, definitions = {}, components = {}, includes = {}, frontmatter = nil }
  local n = #lines
  local start = 1
  if lines[1] and lines[1]:match("^%-%-%-%s*$") then
    for k = 2, n do
      if lines[k]:match("^%-%-%-%s*$") or lines[k]:match("^%.%.%.%s*$") then
        o.frontmatter = { 2, k - 1 }
        start = k + 1
        break
      end
    end
  end
  local in_fence, in_comment = false, false
  for k = start, n do
    local t = lines[k]
    if in_comment then
      if t:find("-->", 1, true) then in_comment = false end
    elseif t:match("^%s*```") or t:match("^%s*~~~") then
      in_fence = not in_fence
    elseif not in_fence then
      if t:find("<!--", 1, true) and not t:find("-->", 1, true) then in_comment = true end
      local hashes, title = t:match("^(#+)%s+(.-)%s*$")
      if hashes and #hashes <= 6 then
        local key = title:match("^!") and not title:match("^!%[")
        if key then title = title:gsub("^!%s*", "") end
        local attrs = title:match("%s*{([^{}]*)}%s*$") or ""
        title = title:gsub("%s*{[^{}]*}%s*$", "")
        local roles = {}
        for r in attrs:gmatch("#([%w_-]+)") do roles[#roles + 1] = r end
        o.headings[#o.headings + 1] = { level = #hashes, title = title, roles = roles, line = k, key = key and true or false }
      else
        local item = t:match("^%s*[-*+]%s+(.*)$")
        local name = item and item:gsub("^{[^{}]*}%s*", ""):gsub("^(%d+%-?%d*)%s*×", "%1x")
          :match("^%d+%-?%d*%s*[xX]%s+[^%[]-%[%[([^%]|#]+)")
        if name then
          o.components[#o.components + 1] = { name = vim.trim(name), line = k }
        end
        local inc, sec = t:match("^%s*!%[%[([^%]#|]+)#?([^%]|]*)%]%]%s*$")
        if inc then o.includes[#o.includes + 1] = { name = vim.trim(inc), section = sec, line = k } end
        local nxt = lines[k + 1]
        if t:match("%S") and nxt and (nxt:match("^:%s") or nxt == ":") and not t:match("^%s")
            and not t:match("^[-*+>|!#:]") and not t:match("^%d+[.)]%s") then
          local term = t:gsub("^{[^{}]*}%s*", ""):gsub("%s*{[^{}]*}%s*$", "")
          local body, last = {}, k + 1
          body[1] = lines[k + 1]:gsub("^:%s?", "")
          while last + 1 <= n do
            local l = lines[last + 1]
            local after = lines[last + 2]
            if l:match("^:%s") or l == ":" then
              body[#body + 1] = ""
              body[#body + 1] = (l:gsub("^:%s?", ""))
            elseif l:match("^%s+%S") then
              body[#body + 1] = (l:gsub("^%s%s?", ""))
            elseif l == "" and after and (after:match("^%s+%S") or after:match("^:%s")) then
              body[#body + 1] = ""
            else
              break
            end
            last = last + 1
          end
          o.definitions[#o.definitions + 1] = { term = vim.trim(term), line = k, body = body }
        end
      end
    end
  end
  return o
end

--- The `name:` entries under a top-level YAML key (values:, symbols:) of a frontmatter or vault.yaml.
function M.yaml_entries(lines, first, last, key)
  local out, inside = {}, false
  for k = first, last do
    local l = lines[k]
    if l:match("^" .. key .. ":%s*$") then
      inside = true
    elseif inside and l:match("^%S") then
      inside = false
    elseif inside then
      local name, value = l:match("^  ([%w_-]+):%s*(.-)%s*$")
      if name then out[#out + 1] = { name = name, value = value } end
    end
  end
  return out
end

local function vault_yaml(root)
  return root and (read_lines(root .. "/vault.yaml") or read_lines(root .. "/vault.yml")) or nil
end

--- Values ({=name}) and symbols (:name:) of the game and its vault: { values = {...}, symbols = {...} }.
function M.definitions_of(lines, file)
  local o = M.outline(lines)
  local out = { values = {}, symbols = {} }
  local seen = { values = {}, symbols = {} }
  local function add(kind, list, from)
    for _, e in ipairs(list) do
      if not seen[kind][e.name] then
        seen[kind][e.name] = true
        out[kind][#out[kind] + 1] = { name = e.name, value = e.value, from = from }
      end
    end
  end
  if o.frontmatter then
    add("values", M.yaml_entries(lines, o.frontmatter[1], o.frontmatter[2], "values"), "this game")
    add("symbols", M.yaml_entries(lines, o.frontmatter[1], o.frontmatter[2], "symbols"), "this game")
  end
  local vy = vault_yaml(file and M.vault_root(file))
  if vy then
    add("values", M.yaml_entries(vy, 1, #vy, "values"), "vault.yaml")
    add("symbols", M.yaml_entries(vy, 1, #vy, "symbols"), "vault.yaml")
  end
  return out
end

--- The outlines of the shared fragments the game includes: { { name, path, outline, lines } }.
function M.fragments(o, file)
  local root = file and M.vault_root(file)
  local out, seen = {}, {}
  if not root then return out end
  for _, inc in ipairs(o.includes) do
    if not seen[inc.name] then
      seen[inc.name] = true
      local path = root .. "/_shared/" .. inc.name .. ".game"
      local fl = read_lines(path)
      if fl then out[#out + 1] = { name = inc.name, path = path, lines = fl, outline = M.outline(fl) } end
    end
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

--- Where a frontmatter line is: "top", "option" (an extension's details) or nil.
function M.frontmatter_level(lines, row, indent)
  if indent == 0 then return "top" end
  local parents, want = {}, indent
  for k = row - 1, 2, -1 do
    local l = lines[k]
    if l:match("%S") and not l:match("^%s*#") then
      local i = #l:match("^%s*")
      if i < want then
        table.insert(parents, 1, vim.trim(l))
        want = i
        if i == 0 then break end
      end
    end
  end
  if #parents == 2 and (parents[1]:match("^extensions:%s*$") or parents[1]:match("^variants:%s*$"))
      and parents[2]:match("^[^%s:#-][^:]*:%s*$") then
    return "option"
  end
  return nil
end

--- What is being completed at the cursor: { kind, start (0-based column), typed } or nil.
--- kind: "term", "section", "fragment", "value", "symbol" or "key" (frontmatter).
function M.context(lines, row, col)
  local before = (lines[row] or ""):sub(1, col)
  local o = M.outline(lines)
  if o.frontmatter and row >= o.frontmatter[1] and row <= o.frontmatter[2] then
    local ind, typed = before:match("^(%s*)([%w_-]*)$")
    if ind then
      local level = M.frontmatter_level(lines, row, #ind)
      if level then return { kind = "key", level = level, start = #ind, typed = typed } end
    end
    return nil
  end
  local s, typed = before:match("()!%[%[([^%]#|]*)$")
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
  return typed == "" or fold(word):sub(1, #fold(typed)) == fold(typed) or word:lower():find(typed:lower(), 1, true) == 1
end

--- Completion items for the cursor: list of { word, abbr, menu, info, kind } (complete-items).
function M.items(lines, row, col, file)
  local ctx = M.context(lines, row, col)
  if not ctx then return nil, nil end
  local out, seen = {}, {}
  local function add(item)
    local k = item.kind_ .. "|" .. fold(item.word)
    if seen[k] or not starts(item.word, ctx.typed) then return end
    seen[k] = true
    item.kind_ = nil
    out[#out + 1] = item
  end
  local o = M.outline(lines)
  local rest = (lines[row] or ""):sub(col + 1)
  if ctx.kind == "term" or ctx.kind == "section" then
    local close = rest:match("^%]%]") and "" or "]]"
    local sources = { { outline = o, from = nil } }
    for _, f in ipairs(M.fragments(o, file)) do sources[#sources + 1] = { outline = f.outline, from = f.name } end
    if ctx.kind == "term" then
      for _, src in ipairs(sources) do
        for _, d in ipairs(src.outline.definitions) do
          add({ word = d.term .. close, abbr = d.term, kind = "d", menu = src.from and ("def · " .. src.from) or "definition",
                info = table.concat(d.body, "\n"), kind_ = "t" })
        end
      end
      for _, src in ipairs(sources) do
        for _, c in ipairs(src.outline.components) do
          add({ word = c.name .. close, abbr = c.name, kind = "c", menu = "component", kind_ = "t" })
        end
      end
    else
      for _, h in ipairs(o.headings) do
        add({ word = h.title .. close, abbr = h.title, kind = "s", menu = "section", kind_ = "s" })
      end
      for _, h in ipairs(o.headings) do
        for _, r in ipairs(h.roles) do
          add({ word = r .. close, abbr = r, kind = "r", menu = "role → " .. h.title, kind_ = "r" })
        end
      end
    end
  elseif ctx.kind == "fragment" then
    local root = file and M.vault_root(file)
    if root then
      for _, path in ipairs(vim.fn.glob(root .. "/_shared/*.game", false, true)) do
        local name = vim.fn.fnamemodify(path, ":t:r")
        if not name:find("%.") then add({ word = name, kind = "f", menu = "fragment", kind_ = "f" }) end
      end
    end
  elseif ctx.kind == "value" then
    local close = rest:match("^%s*}") and "" or "}"
    for _, v in ipairs(M.definitions_of(lines, file).values) do
      add({ word = v.name .. close, abbr = v.name, kind = "v", menu = v.value, info = "value from " .. v.from, kind_ = "v" })
    end
  elseif ctx.kind == "symbol" then
    for _, v in ipairs(M.definitions_of(lines, file).symbols) do
      add({ word = ":" .. v.name .. ":", abbr = ":" .. v.name .. ":", kind = "y", menu = v.value,
            info = "symbol from " .. v.from, kind_ = "y" })
    end
  elseif ctx.kind == "key" then
    local kind = file and file:match("%.sheet$") and "sheet" or "game"
    local present = {}
    for k = o.frontmatter[1], o.frontmatter[2] do
      local ind, key = (lines[k] or ""):match("^(%s*)([%w_-]+)%s*:")
      if key and k ~= row and #ind == ctx.start and M.frontmatter_level(lines, k, #ind) == ctx.level then
        present[key] = true
      end
    end
    for _, k in ipairs(schema_keys(kind, ctx.level)) do
      if not present[k.key] then
        add({ word = k.key .. ": ", abbr = k.key, kind = "k",
              menu = ctx.level == "option" and "detail" or "frontmatter", info = k.description, kind_ = "k" })
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
    local lines = vim.api.nvim_buf_get_lines(0, 0, -1, false)
    local items, ctx = M.items(lines, row, col, vim.api.nvim_buf_get_name(0))
    pending = items or {}
    return ctx and ctx.start or -3
  end
  -- Vim takes the typed text out of the line before this second call: filter by `base` instead
  local typed = base:gsub("^!?%[%[#?", ""):gsub("^{=%s*", "")
  return vim.tbl_filter(function(i) return starts(i.abbr or i.word, typed) end, pending)
end

-- ------------------------------------------------------------------ hover and go to definition

--- The [[reference]] (or ![[fragment]]) under the cursor: { name, section, fragment } or nil.
function M.ref_at(line, col)
  for s, inner, e in line:gmatch("()!?%[%[([^%]]-)%]%]()") do
    if col + 1 >= s and col + 1 < e then
      local fragment = line:sub(s, s) == "!"
      local name = vim.trim((inner:match("^([^|]*)")))
      if fragment then
        local n, sec = name:match("^([^#]*)#?(.*)$")
        return { fragment = true, name = vim.trim(n), section = sec }
      end
      return { name = name }
    end
  end
  return nil
end

local function find_target(lines, file, ref)
  local o = M.outline(lines)
  if ref.fragment then
    local root = file and M.vault_root(file)
    return root and { path = root .. "/_shared/" .. ref.name .. ".game", line = 1 } or nil
  end
  if ref.name:match("^#") then
    local want = fold(ref.name:sub(2))
    for _, h in ipairs(o.headings) do
      if fold(h.title) == want then return { line = h.line, heading = h } end
    end
    for _, h in ipairs(o.headings) do
      for _, r in ipairs(h.roles) do
        if r:lower() == want then return { line = h.line, heading = h } end
      end
    end
    return nil
  end
  local key = fold(ref.name)
  local sources = { { outline = o } }
  for _, f in ipairs(M.fragments(o, file)) do sources[#sources + 1] = { outline = f.outline, path = f.path, lines = f.lines } end
  for _, src in ipairs(sources) do
    for _, d in ipairs(src.outline.definitions) do
      if fold(d.term) == key then return { line = d.line, path = src.path, def = d } end
    end
  end
  for _, src in ipairs(sources) do
    for _, c in ipairs(src.outline.components) do
      if fold(c.name) == key then return { line = c.line, path = src.path, component = c, lines = src.lines } end
    end
  end
  return nil
end
M.find_target = find_target

--- K: the definition of the reference under the cursor in a floating window (else the usual K).
function M.hover()
  local row, col = unpack(vim.api.nvim_win_get_cursor(0))
  local lines = vim.api.nvim_buf_get_lines(0, 0, -1, false)
  local ref = M.ref_at(lines[row], col)
  local t = ref and find_target(lines, vim.api.nvim_buf_get_name(0), ref)
  if not t then
    vim.cmd("normal! K")
    return
  end
  local body
  if t.def then
    body = vim.list_extend({ "**" .. t.def.term .. "**", "" }, t.def.body)
  elseif t.heading then
    body = {}
    for k = t.line, math.min(#lines, t.line + 12) do body[#body + 1] = lines[k] end
  elseif t.component then
    body = { ((t.lines or lines)[t.line]):gsub("^%s+", "") }
  else
    body = { ref.name }
  end
  vim.lsp.util.open_floating_preview(body, "markdown", { border = "rounded", focus_id = "tabula-hover" })
end

--- gd: go to the definition, component line or heading of the reference under the cursor.
function M.goto_definition()
  local row, col = unpack(vim.api.nvim_win_get_cursor(0))
  local lines = vim.api.nvim_buf_get_lines(0, 0, -1, false)
  local ref = M.ref_at(lines[row], col)
  local t = ref and find_target(lines, vim.api.nvim_buf_get_name(0), ref)
  if not t then
    vim.cmd("normal! gd")
    return
  end
  vim.cmd("normal! m'")
  if t.path then vim.cmd.edit(vim.fn.fnameescape(t.path)) end
  vim.api.nvim_win_set_cursor(0, { t.line, 0 })
end

-- ------------------------------------------------------------------ running tabula

local function run(args, input, on_done)
  local cmd = vim.list_extend(vim.deepcopy(M.config.cmd), args)
  local ok, err = pcall(vim.system, cmd, { stdin = input, text = true }, function(res)
    vim.schedule(function() on_done(res) end)
  end)
  if not ok then
    vim.schedule(function()
      vim.notify("tabula: can't run " .. table.concat(M.config.cmd, " ") .. " (" .. tostring(err) .. ")", vim.log.levels.WARN)
    end)
  end
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
  run(args, buffer_text(buf), function(res)
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
        local o = M.outline(vim.api.nvim_buf_get_lines(buf, 0, row + 1, false))
        frontmatter = o.frontmatter == nil and vim.api.nvim_buf_get_lines(buf, 0, 1, false)[1] == "---"
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
end

return M
