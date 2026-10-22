" Vim syntax file
" Language:    Tabula (.game rules and .sheet score sheets)
" Maintainer:  Tabula, https://github.com/Laendrun/tabula
" The format: spec/SPEC.md. Mirrors the VS Code grammar (editors/vscode/syntaxes).

if exists("b:current_syntax")
  finish
endif

let s:cpo_save = &cpo
set cpo&vim
syn case match
syn sync fromstart


" ---- inline: references, conditions, values, symbols, Markdown
syn match  tabulaEscape      /\\[\\{}\[\]*_`|!#]/
syn match  tabulaRef         /\[\[[^#\]|\n][^\]|\n]*\%(|[^\]\n]*\)\?\]\]/ contains=tabulaRefBracket,tabulaRefAlias
syn match  tabulaSectionLink /\[\[#[^\]|\n]\+\%(|[^\]\n]*\)\?\]\]/ contains=tabulaRefBracket,tabulaRefAlias
syn match  tabulaRefBracket  /\[\[\|\]\]/ contained
syn match  tabulaRefAlias    /|[^\]\n]*/ contained
" {3p: one | *: two}: a choice; {2p}, {+ext #role}: a condition (defined last: wins when both match)
syn region tabulaChoice      matchgroup=tabulaBrace start=/\\\@<!{\%(=\)\@!/ end=/}/ oneline contains=tabulaChoiceKey,tabulaChoiceBar,tabulaRef,tabulaSectionLink,tabulaValue,tabulaSymbol,tabulaBold,tabulaItalic,tabulaCode
syn match  tabulaChoiceKey   /\%({\|[|]\)\@<=\s*[^|{}:\n]\+:/ contained
syn match  tabulaChoiceBar   /|/ contained
syn match  tabulaCond        /\\\@<!{\%(=\)\@![^{}:\n]*}/ contains=tabulaRole
syn match  tabulaRole        /#[[:alnum:]_-]\+/ contained
syn match  tabulaValue       /\\\@<!{=\s*[[:alnum:]_-]\+\s*}/
syn match  tabulaSymbol      /\%([[:alpha:]_:\\/]\)\@<!:\a[[:alnum:]_+-]*:\%([[:alnum:]_:/]\)\@!/
syn match  tabulaImage       /!\[[^\]\n]*\]([^)\n]\+)/ contains=tabulaLinkText
syn match  tabulaLink        /\[\@<!\[[^\[\]\n]\+\]([^)\n]\+)/ contains=tabulaLinkText
syn match  tabulaLinkText    /\[\zs[^\]\n]*\ze\]/ contained
syn match  tabulaCode        /`[^`\n]\+`/
syn match  tabulaBold        /\%(\*\*\|__\)\S\%(.\{-}\S\)\?\%(\*\*\|__\)/ contains=tabulaRef,tabulaSectionLink,tabulaCond,tabulaChoice,tabulaValue,tabulaSymbol
syn match  tabulaItalic      /\%([[:alnum:]*]\)\@<!\*[^[:space:]*]\%([^*]\{-}[^[:space:]*]\)\?\*\%([[:alnum:]*]\)\@!/ contains=tabulaRef,tabulaSectionLink,tabulaCond,tabulaValue,tabulaSymbol
syn match  tabulaItalic      /\%([[:alnum:]_]\)\@<!_[^[:space:]_]\%([^_]\{-}[^[:space:]_]\)\?_\%([[:alnum:]_]\)\@!/ contains=tabulaRef,tabulaSectionLink,tabulaCond,tabulaValue,tabulaSymbol
syn cluster tabulaInline contains=tabulaEscape,tabulaRef,tabulaSectionLink,tabulaChoice,tabulaCond,tabulaValue,tabulaSymbol,tabulaImage,tabulaLink,tabulaCode,tabulaBold,tabulaItalic

" ---- lines
syn region tabulaComment     start=/<!--/ end=/-->/ contains=tabulaTodo keepend
syn match  tabulaTodo        /\<\%(TODO\|FIXME\|XXX\)\>/ contained
syn region tabulaFence       start=/^\s*\z(```\|\~\~\~\).*$/ end=/^\s*\z1\s*$/ keepend
syn match  tabulaSectionEnd  /^-\{3,}\s*$/
syn match  tabulaHeading     /^#\{1,6}\s.*$/ contains=tabulaHeadingMark,tabulaKeyBang,@tabulaInline
syn match  tabulaHeadingMark /^#\{1,6}/ contained
syn match  tabulaKeyBang     /\%(^#\{1,6}\s\+\)\@<=!\%(\[\)\@!/ contained
syn match  tabulaTable       /^\s*|.*$/ contains=tabulaTableBar,tabulaTableSep,@tabulaInline
syn match  tabulaTableBar    /|/ contained
syn match  tabulaTableSep    /^\s*|\%(\s*:\?-\+:\?\s*|\)\+\s*$/ contained
" a glossary term: the line above ': definition'
syn match  tabulaTerm        /^[^-*+>|!#:[:space:]<].*\n\ze:\%(\s\|$\)/ contains=tabulaCond,tabulaRole
syn match  tabulaDefMarker   /^:\%(\s\|$\)\@=/ nextgroup=tabulaField skipwhite
" card fields: key:: value, at the top of a definition
syn match  tabulaField       /\%(^\%(:\s\+\|\s\+\)\)\@<=\%([[:alpha:]]\|[^\x00-\x7f]\)[^:\n]\{-}::\%(\s\|$\)\@=/
syn match  tabulaListLine    /^\s*\%([-*+]\|\d\+[.)]\)\s.*$/ contains=tabulaListMark,tabulaCount,tabulaKeyBang,@tabulaInline
syn match  tabulaListMark    /^\s*\%([-*+]\|\d\+[.)]\)\s\+\%(!\%(\[\)\@!\)\?/ contained contains=tabulaListKey
syn match  tabulaListKey     /!/ contained
syn match  tabulaCount       /\%(^\s*[-*+]\s\+\%({[^{}]*}\s*\)\?\)\@<=\d\+\%(-\d\+\)\?\s*[xX×]\ze\s/ contained
syn match  tabulaQuote       /^\s*>.*$/ contains=tabulaQuoteMark,tabulaCallout,tabulaListMark,@tabulaInline
syn match  tabulaQuoteMark   /^\s*>/ contained
syn match  tabulaCallout     /\%(^\s*>\s*\)\@<=\[![^\]\n]*\].*$/ contained contains=@tabulaInline
syn match  tabulaKeyRule     /^\s*!\%(\[\)\@!.*$/ contains=tabulaKeyRuleBang,@tabulaInline
syn match  tabulaKeyRuleBang /^\s*!/ contained
syn match  tabulaInclude     /^\s*!\[\[[^\]#|\n]\+\%(#[^\]|\n]\+\)\?\]\]\s*$/
" sheets: {player} / {n} columns, {r} rounds, // shaded, < and ^ merged cells
syn match  tabulaSheetCell   /{\%(player\|n\|r\)}\|\%(^\|\s\)\zs\%(\/\/\|<\|\^\)\ze\s*|/ containedin=tabulaTable

" ---- frontmatter (YAML), only at the very top (defined last: wins over "---" and the rest)
syn include @tabulaYaml syntax/yaml.vim
unlet! b:current_syntax
syn region tabulaFrontmatter matchgroup=tabulaFrontmatterDelim start=/\%^---\s*$/ end=/^\%(---\|\.\.\.\)\s*$/ keepend contains=@tabulaYaml

hi def link tabulaFrontmatterDelim PreProc
hi def link tabulaComment     Comment
hi def link tabulaTodo        Todo
hi def link tabulaFence       String
hi def link tabulaSectionEnd  PreProc
hi def link tabulaHeading     Title
hi def link tabulaHeadingMark Delimiter
hi def link tabulaKeyBang     Exception
hi def link tabulaTableBar    Delimiter
hi def link tabulaTableSep    Delimiter
hi def link tabulaTerm        Function
hi def link tabulaDefMarker   Delimiter
hi def link tabulaField       Keyword
hi def link tabulaListMark    Delimiter
hi def link tabulaListKey     Exception
hi def link tabulaCount       Number
hi def link tabulaQuoteMark   Comment
hi def link tabulaCallout     Special
hi def      tabulaKeyRule     term=bold cterm=bold gui=bold
hi def link tabulaKeyRuleBang Exception
hi def link tabulaInclude     Include
hi def link tabulaSheetCell   Special
hi def link tabulaEscape      SpecialChar
hi def link tabulaRef         Identifier
hi def link tabulaRefBracket  Delimiter
hi def link tabulaRefAlias    String
hi def link tabulaSectionLink Label
hi def link tabulaBrace       PreProc
hi def link tabulaChoiceKey   PreProc
hi def link tabulaChoiceBar   PreProc
hi def link tabulaCond        PreProc
hi def link tabulaRole        Type
hi def link tabulaValue       Constant
hi def link tabulaSymbol      Character
hi def link tabulaImage       Underlined
hi def link tabulaLink        Underlined
hi def link tabulaLinkText    String
hi def link tabulaCode        String
hi def      tabulaBold        term=bold cterm=bold gui=bold
hi def      tabulaItalic      term=italic cterm=italic gui=italic

let b:current_syntax = "tabula"
let &cpo = s:cpo_save
unlet s:cpo_save
