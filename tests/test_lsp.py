"""`tabula lsp`: the language server, end to end (JSON-RPC over stdin/stdout, as an editor talks to it)."""
import pytest

pytest.importorskip("pygls")

from lsp_client import Client  # noqa: E402

GAME = """---
title: G
players: 2-4
values:
  main: {2p: 7, "*": 5}
---
# Matériel {#components}

- 2x [[Pion]]
- 🎲 1x [[dé]]

![[deck#Glossaire]]

# Jeu {#play}

Distribuez {=main} cartes. Lancez le 🎲 [[dé]], prenez un [[Pion]] et une [[crad]].

# Glossaire {#glossary}

Pion
: Une figurine.

Dé
: points:: 6
  Un cube.
"""


@pytest.fixture
def vault(tmp_path):
    (tmp_path / "vault.yaml").write_text("name: T\n", encoding="utf-8")
    (tmp_path / "_shared").mkdir()
    (tmp_path / "_shared" / "deck.game").write_text("# Glossaire\n\nCarte\n: Une carte.\n", encoding="utf-8")
    (tmp_path / "g").mkdir()
    f = tmp_path / "g" / "g.game"
    f.write_text(GAME, encoding="utf-8")
    return tmp_path, f


@pytest.fixture
def client(vault):
    root, f = vault
    c = Client(root, {"images": "html"})
    c.open(f, GAME)
    yield c, f
    c.close()


LINES = GAME.split("\n")
PLAY = LINES.index(next(l for l in LINES if l.startswith("Distribuez")))


def u16(text: str, chars: int) -> int:
    return len(text[:chars].encode("utf-16-le")) // 2


def test_capabilities_and_problems_as_you_type(client):
    c, f = client
    caps = c.capabilities
    for k in ("completionProvider", "hoverProvider", "definitionProvider", "referencesProvider", "renameProvider",
              "codeActionProvider", "documentFormattingProvider", "documentSymbolProvider", "inlayHintProvider",
              "codeLensProvider", "documentLinkProvider", "foldingRangeProvider"):
        assert caps.get(k), k
    d = c.wait_diagnostics(f, lambda d: any("crad" in x["message"] for x in d))
    crad = next(x for x in d if "crad" in x["message"])
    line = LINES[PLAY]
    assert crad["range"]["start"] == {"line": PLAY, "character": u16(line, line.index("[[crad]]"))}   # after the 🎲
    assert crad["source"] == "tabula" and crad["severity"] == 2
    c.change(f, GAME.replace("[[crad]]", "[[Pion]]"), 2)                      # fixed before saving
    c.wait_diagnostics(f, lambda d: not any("crad" in x["message"] for x in d))


def test_completion(client):
    c, f = client
    text = GAME + "\nVoir [[\n"
    c.change(f, text, 2)
    n = text.split("\n").index("Voir [[")
    r = c.request("textDocument/completion", c.at(f, n, 7))
    labels = [i["label"] for i in r["items"]]
    assert labels[:3] == ["Pion", "Dé", "Carte"]                              # definitions, the fragment's too
    assert r["items"][0]["textEdit"]["newText"] == "Pion]]"
    c.change(f, text.replace("Voir [[", "Prenez {="), 3)
    r = c.request("textDocument/completion", c.at(f, n, 9))
    assert [(i["label"], i["textEdit"]["newText"]) for i in r["items"]] == [("main", "main}")]
    c.change(f, text.replace("Voir [[", "Voir [[#"), 4)
    labels = [i["label"] for i in c.request("textDocument/completion", c.at(f, n, 8))["items"]]
    assert "Jeu" in labels and "play" in labels


def test_hover_definition_references(client):
    c, f = client
    line = LINES[PLAY]
    col = u16(line, line.index("[[dé]]") + 3)
    h = c.request("textDocument/hover", c.at(f, PLAY, col))
    assert h["contents"]["value"].startswith("**Dé**\n\n**points:** 6\n\nUn cube.")
    d = c.request("textDocument/definition", c.at(f, PLAY, col))
    assert d[0]["range"]["start"]["line"] == LINES.index("Dé")
    refs = c.request("textDocument/references", {**c.at(f, PLAY, col), "context": {"includeDeclaration": True}})
    assert sorted(r["range"]["start"]["line"] for r in refs) == sorted([LINES.index("Dé"), 9, PLAY])
    inc = c.request("textDocument/definition", c.at(f, LINES.index("![[deck#Glossaire]]"), 5))
    assert inc[0]["uri"].endswith("_shared/deck.game")
    hv = c.request("textDocument/hover", c.at(f, PLAY, u16(line, line.index("{=main}") + 3)))
    assert hv["contents"]["value"] == "**main** = `2p 7 · * 5`\n\nfrom this file"


def test_rename(client):
    c, f = client
    line = LINES[PLAY]
    col = u16(line, line.index("[[Pion]]") + 3)
    prep = c.request("textDocument/prepareRename", c.at(f, PLAY, col))
    assert prep["placeholder"] == "Pion"
    edit = c.request("textDocument/rename", {**c.at(f, PLAY, col), "newName": "Meeple"})
    texts = sorted(e["newText"] for e in edit["changes"][f.as_uri()])
    assert texts == ["Meeple", "[[Meeple]]", "[[Meeple]]"]
    with pytest.raises(RuntimeError, match="Put the cursor"):
        c.request("textDocument/prepareRename", c.at(f, 1, 0))


def test_quick_fixes_and_add_word(client, vault):
    c, f = client
    d = c.wait_diagnostics(f, lambda d: any("crad" in x["message"] for x in d))
    crad = [x for x in d if "crad" in x["message"]]
    acts = c.request("textDocument/codeAction", {"textDocument": {"uri": f.as_uri()}, "range": crad[0]["range"],
                                                 "context": {"diagnostics": crad}})
    titles = [a["title"] for a in acts]
    assert "Define 'Crad' in the glossary" in titles
    c.request("workspace/executeCommand", {"command": "tabula.addWord", "arguments": [f.as_uri(), "Zorblax"]})
    assert "Zorblax" in (vault[0] / "words.txt").read_text(encoding="utf-8")


def test_formatting_outline_hints_lenses_links(client):
    c, f = client
    messy = GAME.replace("# Jeu {#play}\n", "# Jeu {#play}\n\n\n")
    c.change(f, messy, 2)
    edits = c.request("textDocument/formatting", {"textDocument": {"uri": f.as_uri()}, "options": {"tabSize": 2, "insertSpaces": True}})
    assert edits and "\n\n\n\n" not in edits[0]["newText"]
    c.change(f, GAME, 3)
    syms = c.request("textDocument/documentSymbol", {"textDocument": {"uri": f.as_uri()}})
    assert [s["name"] for s in syms] == ["Matériel", "Jeu", "Glossaire"]
    assert [s["name"] for s in syms[2]["children"]] == ["Pion", "Dé"]
    hints = c.request("textDocument/inlayHint", {"textDocument": {"uri": f.as_uri()},
                                                 "range": {"start": {"line": 0, "character": 0}, "end": {"line": 99, "character": 0}}})
    assert [h["label"] for h in hints] == ["= 2p 7 · * 5"]
    lenses = c.request("textDocument/codeLens", {"textDocument": {"uri": f.as_uri()}})
    assert [(l["range"]["start"]["line"], l["command"]["title"]) for l in lenses] == [
        (LINES.index("Pion"), "used 2 times"), (LINES.index("Dé"), "used 2 times")]
    assert lenses[0]["command"]["command"] == "tabula.showReferences"
    links = c.request("textDocument/documentLink", {"textDocument": {"uri": f.as_uri()}})
    assert links[0]["target"].endswith("_shared/deck.game")
    folds = c.request("textDocument/foldingRange", {"textDocument": {"uri": f.as_uri()}})
    assert any(r["startLine"] == 6 for r in folds)
    o = c.request("tabula/outline", {"uri": f.as_uri()})
    assert o["outline"] == 1 and [d["term"] for d in o["definitions"]] == ["Pion", "Dé"]


def test_characters_when_the_client_offers_utf32(vault):
    root, f = vault
    c = Client(root, encodings=("utf-32", "utf-16"))
    try:
        c.open(f, GAME)
        line = LINES[PLAY]
        col = line.index("[[dé]]") + 3                       # characters, not UTF-16 units
        h = c.request("textDocument/hover", c.at(f, PLAY, col))
        assert h["contents"]["value"].startswith("**Dé**")
        assert h["range"]["start"]["character"] == line.index("[[dé]]")
    finally:
        c.close()
