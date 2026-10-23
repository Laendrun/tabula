"""`tabula lsp`: a language server (Language Server Protocol, over stdin/stdout) for .game and .sheet files.

It keeps the open files in memory and answers the editor with the same parser as every other command:
problems as you type (tabula check), completion, hovers, go to definition, references, rename, quick fixes,
formatting (tabula fmt), the outline, folding, links, inline hints and use counts. VS Code (editors/vscode),
Neovim (editors/nvim) and any editor with an LSP client can use it.

Needs the optional pygls package: `pipx inject tabula pygls` (or `pip install 'tabula[lsp]'`).

Settings (initializationOptions, or `tabula` in workspace/didChangeConfiguration):
    spell        check spelling too (tabula check --spell)
    definitions  every component needs a definition (tabula check --definitions)
    images       how hovers show pictures: "html" (VS Code), "markdown" or "none" (their path)
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from urllib.parse import unquote, urlparse

from . import editor
from ._version import __version__

DEBOUNCE = 0.25            # seconds of quiet before checking a changed file


def uri_to_path(uri: str) -> Path:
    p = urlparse(uri)
    path = unquote(p.path)
    if sys.platform == "win32" and path.startswith("/") and len(path) > 2 and path[2] == ":":
        path = path[1:]
    return Path(path)


def path_to_uri(path) -> str:
    return Path(path).resolve().as_uri()


def build_server():
    from lsprotocol import types as T
    from pygls.lsp.server import LanguageServer

    from .check import check_all_languages, check_setting  # noqa: F401  (check_setting: vault/game settings)
    from .fmt import format_game
    from .outline import outline_file
    from .sheet import check_sheet, load_sheet
    from .source import UNSAVED
    from .syntax import split_lang
    from .vault import open_vault

    server = LanguageServer("tabula", __version__, text_document_sync_kind=T.TextDocumentSyncKind.Full)
    state = {"settings": {"spell": False, "definitions": False, "images": "none"}, "outlines": {},
             "published": {}, "timers": {}}

    # ---------------------------------------------------------------- documents, outlines, positions

    def doc_of(uri: str):
        return server.workspace.get_text_document(uri)

    def remember(uri: str):
        """Make the unsaved text of a document what every tabula function reads for that file."""
        doc = doc_of(uri)
        UNSAVED[uri_to_path(uri).resolve()] = doc.source
        return doc

    def outline(uri: str):
        doc = remember(uri)
        cached = state["outlines"].get(uri)
        if cached and cached[0] == doc.version and cached[2] == doc.source:
            return cached[1]
        path = uri_to_path(uri)
        try:
            o = outline_file(path, open_vault(None, str(path)))
        except Exception as e:                           # never let one file stop the server
            server.window_log_message(T.LogMessageParams(type=T.MessageType.Warning, message=f"tabula outline {path}: {e}"))
            o = None
        state["outlines"][uri] = (doc.version, o, doc.source)
        return o

    def here(doc, pos):
        """A client position as (line, column in characters)."""
        p = doc.position_codec.position_from_client_units(doc.lines, pos)
        return p.line, p.character

    def rng(doc, line: int, start: int, end: int):
        """A range on a line (columns in characters) in the client's units."""
        r = T.Range(T.Position(line, start), T.Position(line, end))
        if line >= len(doc.lines):
            return r
        return doc.position_codec.range_to_client_units(doc.lines, r)

    def line_of(doc, line: int) -> str:
        return doc.lines[line].rstrip("\r\n") if line < len(doc.lines) else ""

    def loc(file, line: int, doc_uri: str):
        uri = path_to_uri(file) if file else doc_uri
        return T.Location(uri, T.Range(T.Position(line, 0), T.Position(line, 0)))

    # ---------------------------------------------------------------- settings

    @server.feature(T.INITIALIZE)
    def initialize(params: T.InitializeParams):
        opts = params.initialization_options or {}
        if isinstance(opts, dict):
            state["settings"].update({k: v for k, v in opts.items() if k in state["settings"]})

    @server.feature(T.WORKSPACE_DID_CHANGE_CONFIGURATION)
    def configuration(params: T.DidChangeConfigurationParams):
        s = params.settings
        s = s.get("tabula", s) if isinstance(s, dict) else {}
        if isinstance(s, dict):
            state["settings"].update({k: v for k, v in s.items() if k in state["settings"]})
        for uri in list(server.workspace.text_documents):
            schedule(uri, 0)

    # ---------------------------------------------------------------- problems (tabula check)

    def check(uri: str):
        state["timers"].pop(uri, None)
        if uri not in server.workspace.text_documents:
            return
        remember(uri)
        path = uri_to_path(uri)
        s = state["settings"]
        try:
            vault = open_vault(None, str(path))
            if path.suffix == ".sheet":
                issues, files = list(check_sheet(load_sheet(path, vault), vault)), [path]
            else:
                slug, lang = split_lang(path.stem)
                default = path.parent / f"{slug}.game"
                start = default if lang and default.is_file() else path
                game, issues = check_all_languages(vault, start, bool(s["definitions"]), bool(s["spell"]))
                files = [path] + [path.parent / (f"{game.slug}.game" if l == game.default_language
                                                 else f"{game.slug}.{l}.game") for l in game.languages]
        except SystemExit as e:
            server.window_log_message(T.LogMessageParams(type=T.MessageType.Warning, message=str(e)))
            return
        except Exception as e:
            server.window_log_message(T.LogMessageParams(type=T.MessageType.Error, message=f"tabula check {path}: {e!r}"))
            return
        by_file: dict = {str(Path(f).resolve()): [] for f in files}
        for i in issues:
            by_file.setdefault(str(Path(i.path).resolve()), []).append(i)
        published = set()
        for f, found in by_file.items():
            furi = path_to_uri(f)
            fdoc = doc_of(furi) if furi in server.workspace.text_documents else None
            lines = fdoc.lines if fdoc else _disk_lines(f)
            diags = []
            for i in found:
                line = max(0, (i.line or 1) - 1)
                text = lines[line].rstrip("\r\n") if line < len(lines) else ""
                a, b = editor.issue_columns(text, i.msg)
                r = T.Range(T.Position(line, a), T.Position(line, max(b, a + 1)))
                if fdoc and line < len(fdoc.lines):
                    r = fdoc.position_codec.range_to_client_units(fdoc.lines, r)
                sev = {"error": T.DiagnosticSeverity.Error, "warning": T.DiagnosticSeverity.Warning}.get(
                    i.level, T.DiagnosticSeverity.Information)
                diags.append(T.Diagnostic(range=r, message=i.msg, severity=sev, source="tabula"))
            server.text_document_publish_diagnostics(T.PublishDiagnosticsParams(uri=furi, diagnostics=diags))
            published.add(furi)
        for old in state["published"].get(uri, set()) - published:       # files no longer concerned
            server.text_document_publish_diagnostics(T.PublishDiagnosticsParams(uri=old, diagnostics=[]))
        state["published"][uri] = published

    def schedule(uri: str, delay: float = DEBOUNCE):
        t = state["timers"].pop(uri, None)
        if t:
            t.cancel()
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            check(uri)
            return
        state["timers"][uri] = loop.call_later(delay, check, uri)

    @server.feature(T.TEXT_DOCUMENT_DID_OPEN)
    def did_open(params: T.DidOpenTextDocumentParams):
        schedule(params.text_document.uri, 0)

    @server.feature(T.TEXT_DOCUMENT_DID_CHANGE)
    def did_change(params: T.DidChangeTextDocumentParams):
        remember(params.text_document.uri)
        schedule(params.text_document.uri)

    @server.feature(T.TEXT_DOCUMENT_DID_SAVE)
    def did_save(params: T.DidSaveTextDocumentParams):
        for uri in list(server.workspace.text_documents):       # a fragment or a translation may have changed
            schedule(uri, 0)

    @server.feature(T.TEXT_DOCUMENT_DID_CLOSE)
    def did_close(params: T.DidCloseTextDocumentParams):
        uri = params.text_document.uri
        UNSAVED.pop(uri_to_path(uri).resolve(), None)
        state["outlines"].pop(uri, None)
        t = state["timers"].pop(uri, None)
        if t:
            t.cancel()

    # ---------------------------------------------------------------- completion and hover

    KINDS = {"definition": T.CompletionItemKind.Reference, "component": T.CompletionItemKind.Constant,
             "section": T.CompletionItemKind.Module, "role": T.CompletionItemKind.Keyword,
             "file": T.CompletionItemKind.File, "property": T.CompletionItemKind.Property,
             "symbol": T.CompletionItemKind.EnumMember, "constant": T.CompletionItemKind.Constant}

    def fragment_outline(fp):
        try:
            return outline_file(fp, open_vault(None, str(fp)), depth=3)
        except Exception:
            return None

    @server.feature(T.TEXT_DOCUMENT_COMPLETION, T.CompletionOptions(trigger_characters=["[", "#", "=", ":"]))
    def completion(params: T.CompletionParams):
        uri = params.text_document.uri
        o = outline(uri)
        if not o:
            return None
        doc = doc_of(uri)
        line, col = here(doc, params.position)
        path = uri_to_path(uri)
        root = Path(o["vault"])
        items = []
        for it in editor.completion(o, line_of(doc, line), line, col, path, root, fragment_outline):
            ci = T.CompletionItem(
                label=it["label"], kind=KINDS.get(it["kind"]), detail=it["detail"] or None,
                documentation=T.MarkupContent(T.MarkupKind.Markdown, it["doc"]) if it["doc"] else None,
                text_edit=T.TextEdit(rng(doc, line, it["start"], it["end"]), it["insert"]),
                sort_text=it.get("sort"), filter_text=it.get("filter"))
            items.append(ci)
        return T.CompletionList(is_incomplete=False, items=items)

    @server.feature(T.TEXT_DOCUMENT_HOVER)
    def hover(params: T.HoverParams):
        uri = params.text_document.uri
        o = outline(uri)
        if not o:
            return None
        doc = doc_of(uri)
        line, col = here(doc, params.position)
        h = editor.hover(o, line_of(doc, line), line, col, state["settings"]["images"])
        if not h:
            return None
        body, a, b = h
        return T.Hover(contents=T.MarkupContent(T.MarkupKind.Markdown, body), range=rng(doc, line, a, b))

    # ---------------------------------------------------------------- go to definition, references, rename

    @server.feature(T.TEXT_DOCUMENT_DEFINITION)
    def definition(params: T.DefinitionParams):
        uri = params.text_document.uri
        o = outline(uri)
        if not o:
            return None
        doc = doc_of(uri)
        line, col = here(doc, params.position)
        inc = editor.include_at(o, line)
        if inc and inc.get("file"):
            return [loc(inc["file"], inc.get("section_line") or 0, uri)]
        ref = editor.ref_at(o, line, col)
        found = editor.targets(o, ref) if ref else []
        return [loc(f, l, uri) for f, l in found] or None

    @server.feature(T.TEXT_DOCUMENT_REFERENCES)
    def references(params: T.ReferenceParams):
        uri = params.text_document.uri
        o = outline(uri)
        if not o:
            return None
        doc = doc_of(uri)
        line, col = here(doc, params.position)
        occ = editor.occurrences(o, line, col)
        if not occ:
            return None
        wanted = (occ["definitions"] if params.context.include_declaration else []) + occ["references"]
        return [T.Location(uri, rng(doc, r["line"], r["start"], r["end"])) for r in wanted]

    @server.feature(T.TEXT_DOCUMENT_PREPARE_RENAME)
    def prepare_rename(params: T.PrepareRenameParams):
        uri = params.text_document.uri
        o = outline(uri)
        doc = doc_of(uri)
        line, col = here(doc, params.position)
        try:
            t = editor.rename_target(o or {"references": [], "definitions": [], "headings": []}, line, col)
        except editor.RenameError as e:
            raise ValueError(str(e))
        return T.PrepareRenamePlaceholder(range=rng(doc, line, t["start"], t["end"]),
                                          placeholder=t.get("placeholder") or t["name"])

    @server.feature(T.TEXT_DOCUMENT_RENAME)
    def rename(params: T.RenameParams):
        uri = params.text_document.uri
        o = outline(uri)
        doc = doc_of(uri)
        line, col = here(doc, params.position)
        try:
            edits = editor.rename_edits(o, line, col, params.new_name)
        except editor.RenameError as e:
            raise ValueError(str(e))
        return T.WorkspaceEdit(changes={uri: [T.TextEdit(rng(doc, e["line"], e["start"], e["end"]), e["text"])
                                              for e in edits]})

    # ---------------------------------------------------------------- quick fixes and commands

    def text_edits(doc, edits):
        out = []
        for e in edits:
            if e["line"] >= len(doc.lines):                      # past the end: appended
                ends = doc.source.endswith("\n") or not doc.source
                pos = T.Position(len(doc.lines), 0) if ends else T.Position(len(doc.lines) - 1, len(line_of(doc, len(doc.lines) - 1)))
                out.append(T.TextEdit(T.Range(pos, pos), ("" if ends else "\n") + e["text"]))
            else:
                out.append(T.TextEdit(rng(doc, e["line"], e["start"], e["end"]), e["text"]))
        return out

    @server.feature(T.TEXT_DOCUMENT_CODE_ACTION,
                    T.CodeActionOptions(code_action_kinds=[T.CodeActionKind.QuickFix]))
    def code_action(params: T.CodeActionParams):
        uri = params.text_document.uri
        mine = [d for d in params.context.diagnostics if d.source == "tabula"]
        if not mine:
            return None
        o = outline(uri)
        if not o:
            return None
        doc = doc_of(uri)
        lines = [l.rstrip("\r\n") for l in doc.lines]
        actions = []
        for d in mine:
            line, a = here(doc, d.range.start)
            _, b = here(doc, d.range.end)
            for f in editor.quick_fixes(lines, o, line, d.message, a, b):
                act = T.CodeAction(title=f["title"], kind=T.CodeActionKind.QuickFix, diagnostics=[d],
                                   is_preferred=bool(f.get("preferred")))
                if f.get("add_word"):
                    act.command = T.Command(title=f["title"], command="tabula.addWord", arguments=[uri, f["add_word"]])
                else:
                    act.edit = T.WorkspaceEdit(changes={uri: text_edits(doc, f["edits"])})
                actions.append(act)
        return actions

    @server.command("tabula.addWord")
    def add_word(uri: str, word: str):
        o = outline(uri)
        root = Path(o["vault"]) if o else uri_to_path(uri).parent
        f = editor.add_word(root, word)
        server.window_show_message(T.ShowMessageParams(type=T.MessageType.Info, message=f"'{word}' added to {f}"))
        for u in list(server.workspace.text_documents):
            schedule(u, 0)

    # ---------------------------------------------------------------- formatting (tabula fmt)

    @server.feature(T.TEXT_DOCUMENT_FORMATTING)
    def formatting(params: T.DocumentFormattingParams):
        uri = params.text_document.uri
        doc = remember(uri)
        text = doc.source
        new, safe = format_game(uri_to_path(uri), text)
        if not safe:
            server.window_show_message(T.ShowMessageParams(
                type=T.MessageType.Warning, message="tabula: not formatted, the result would read differently (please report it)"))
            return []
        if new == text:
            return []
        end_line = len(doc.lines)
        return [T.TextEdit(T.Range(T.Position(0, 0), T.Position(end_line, 0)), new)]

    # ---------------------------------------------------------------- outline view, folding, links, hints, lenses

    SYMBOL_KINDS = {"section": T.SymbolKind.Namespace, "term": T.SymbolKind.Field, "component": T.SymbolKind.Constant}

    @server.feature(T.TEXT_DOCUMENT_DOCUMENT_SYMBOL)
    def document_symbols(params: T.DocumentSymbolParams):
        uri = params.text_document.uri
        o = outline(uri)
        if not o:
            return []
        doc = doc_of(uri)

        def conv(s):
            full = T.Range(T.Position(s["line"], 0), T.Position(s["end"], len(line_of(doc, s["end"]))))
            sel = T.Range(T.Position(s["line"], 0), T.Position(s["line"], len(line_of(doc, s["line"]))))
            return T.DocumentSymbol(name=s["name"], detail=s["detail"] or None, kind=SYMBOL_KINDS[s["kind"]],
                                    range=full, selection_range=sel, children=[conv(c) for c in s["children"]])
        return [conv(s) for s in editor.symbols(o)]

    @server.feature(T.TEXT_DOCUMENT_FOLDING_RANGE)
    def folding_ranges(params: T.FoldingRangeParams):
        o = outline(params.text_document.uri)
        return [T.FoldingRange(start_line=a, end_line=b) for a, b in editor.folding(o)] if o else []

    @server.feature(T.TEXT_DOCUMENT_DOCUMENT_LINK)
    def document_links(params: T.DocumentLinkParams):
        uri = params.text_document.uri
        o = outline(uri)
        if not o:
            return []
        doc = doc_of(uri)
        out = []
        for l in o["links"]:
            target = l.get("file") or l.get("path")
            if target and l.get("exists"):
                out.append(T.DocumentLink(range=rng(doc, l["line"], l["start"], l["end"]), target=path_to_uri(target),
                                          tooltip="Open the shared fragment" if l["kind"] == "fragment" else "Open the image"))
        return out

    @server.feature(T.TEXT_DOCUMENT_INLAY_HINT)
    def inlay_hints(params: T.InlayHintParams):
        uri = params.text_document.uri
        o = outline(uri)
        if not o:
            return []
        doc = doc_of(uri)
        a, b = params.range.start.line, params.range.end.line
        out = []
        for h in o["hints"]:
            if a <= h["line"] <= b:
                pos = rng(doc, h["line"], h["character"], h["character"]).start
                out.append(T.InlayHint(position=pos, label=h["label"], tooltip=h.get("tooltip") or None, padding_left=True))
        return out

    @server.feature(T.TEXT_DOCUMENT_CODE_LENS)
    def code_lens(params: T.CodeLensParams):
        uri = params.text_document.uri
        o = outline(uri)
        if not o:
            return []
        doc = doc_of(uri)
        out = []
        for u in editor.use_counts(o):
            n = u["count"]
            title = "not used" if n == 0 else "used once" if n == 1 else f"used {n} times"
            r = T.Range(T.Position(u["line"], 0), T.Position(u["line"], 0))
            locs = [T.Location(uri, rng(doc, x["line"], x["start"], x["end"])) for x in u["refs"]]
            cmd = (T.Command(title=title, command="tabula.showReferences", arguments=[uri, r.start, locs]) if n
                   else T.Command(title=title, command=""))
            out.append(T.CodeLens(range=r, command=cmd))
        return out

    # ---------------------------------------------------------------- for the editors' own features

    @server.feature("tabula/outline")
    def outline_request(params):
        """The outline of an open document (VS Code uses it for pasted images)."""
        uri = params.get("uri") if isinstance(params, dict) else getattr(params, "uri", None)
        return outline(uri) if uri else None

    return server


def _disk_lines(f) -> list[str]:
    try:
        return Path(f).read_text(encoding="utf-8", errors="replace").splitlines(keepends=True)
    except OSError:
        return []


def cmd_lsp(args) -> int:
    try:
        import pygls  # noqa: F401
    except ImportError:
        print("tabula: the language server needs the pygls package: pipx inject tabula pygls "
              "(or pip install 'tabula[lsp]')", file=sys.stderr)
        return 2
    build_server().start_io()
    return 0
