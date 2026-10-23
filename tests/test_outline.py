"""`tabula outline FILE --json`: what editors read instead of parsing the format themselves."""
import io
import json
import sys

import tabula

GAME = """---
title: G
players: 2-4
values:
  main: {2p: 7, "*": 5}
symbols:
  gold: media/gold.png
extensions:
  pandora:
    description: P
    year: 2019
---
# Matériel {#components}

- 10x [[Attaque]]
  - 6x [[Attaque 2x]]
  - 3x [[Contre]]
- 2x [[Pion]] — rouges

![[deck#Glossaire]]

```
[[not a reference]]
```

<!-- [[nor this]] -->

# Jeu {#play}

Distribuez {=main} cartes, 🎲 [[dés]] et [[Pion|pions]]. Voir [[#Glossaire]]. `[[code]]` :gold:

![box](media/box.png)

<!-- TODO: finir -->

# Glossaire {#glossary}

Attaque
: avec::
  - [[Attaque 2x]]
  - {+pandora} [[Contre]]

Attaque 2x
: avec:: 2
  image:: media/a2.png
  Deux tours.

## Pandora {+pandora}

Contre
: avec:: 1
  Annule.

Dé
: Un cube.
"""


def make(tmp_path, files):
    root = tmp_path / "v"
    for name, text in files.items():
        (root / name).parent.mkdir(parents=True, exist_ok=True)
        (root / name).write_text(text, encoding="utf-8")
    return root


def outline(capsys, root, file, stdin=None, monkeypatch=None):
    args = ["--vault", str(root), "outline", str(root / file), "--json"]
    if stdin is not None:
        monkeypatch.setattr(sys, "stdin", io.TextIOWrapper(io.BytesIO(stdin.encode("utf-8"))))
        args.append("--stdin")
    assert tabula.main(args) == 0
    return json.loads(capsys.readouterr().out)


def test_structure(tmp_path, capsys):
    root = make(tmp_path, {"g/g.game": GAME, "g/media/a2.png": "x",
                           "_shared/deck.game": "# Glossaire\n\nCarte\n: Une carte.\n"})
    o = outline(capsys, root, "g/g.game")
    assert o["outline"] == 1 and o["kind"] == "game"
    assert [(h["title"], h["level"], h["roles"], h["cond"]) for h in o["headings"]] == [
        ("Matériel", 1, ["components"], ""), ("Jeu", 1, ["play"], ""), ("Glossaire", 1, ["glossary"], ""),
        ("Pandora", 2, [], "+pandora")]
    lines = GAME.split("\n")
    assert lines[o["headings"][0]["line"]] == "# Matériel {#components}"
    assert [d["term"] for d in o["definitions"]] == ["Attaque", "Attaque 2x", "Contre", "Dé"]
    assert [(c["name"], c["quantity"], c["parent"]) for c in o["components"]] == [
        ("Attaque", "10", None), ("Attaque 2x", "6", "Attaque"), ("Contre", "3", "Attaque"), ("Pion", "2", None)]
    assert o["components"][3]["text"] == "2x Pion — rouges"


def test_references_with_columns_in_characters(tmp_path, capsys):
    root = make(tmp_path, {"g/g.game": GAME})
    o = outline(capsys, root, "g/g.game")
    names = [(r["name"], r["section"], r["alias"]) for r in o["references"]]
    assert ("not a reference", False, None) not in names and ("nor this", False, None) not in names
    assert ("code", False, None) not in names
    assert ("Glossaire", True, None) in names and ("Pion", False, "pions") in names
    des = next(r for r in o["references"] if r["name"] == "dés")
    line = GAME.split("\n")[des["line"]]
    assert line[des["start"]:des["end"]] == "[[dés]]" and line[des["name_start"]:des["name_end"]] == "dés"
    assert des["fold"] == next(d for d in o["definitions"] if d["term"] == "Dé")["fold"]     # dés matches Dé


def test_hints_totals_values_links_todos(tmp_path, capsys):
    root = make(tmp_path, {"g/g.game": GAME, "g/media/a2.png": "x", "vault.yaml": "values:\n  target: 100\n"})
    o = outline(capsys, root, "g/g.game")
    labels = [h["label"] for h in o["hints"]]
    assert "= 2p 7 · * 5" in labels and "parts: 9 ≠ 10" in labels and "Σ 3 (base game: 2)" in labels
    tot = next(f for f in o["definitions"][0]["fields"] if f["key"] == "avec")["total"]
    assert tot["all"] == "3" and tot["base"] == "2" and [p["card"] for p in tot["parts"]] == ["Attaque 2x", "Contre"]
    assert "**avec:** Σ 3 (base game: 2)" in o["definitions"][0]["markdown"]
    assert [(v["name"], v["from"]) for v in o["values"]] == [("main", "this file"), ("target", "vault.yaml")]
    assert o["symbols"][0]["name"] == "gold" and o["symbols"][0]["image"].endswith("media/gold.png")
    pic = o["definitions"][1]["image"]
    assert pic["src"] == "media/a2.png" and pic["exists"] is True
    links = {(l["kind"], l.get("src")) for l in o["links"]}
    assert ("image", "media/box.png") in links and ("image", "media/a2.png") in links
    assert o["todos"] == [{"line": GAME.split("\n").index("<!-- TODO: finir -->"), "text": "finir"}]
    assert GAME.split("\n")[o["glossary_line"]] == "## Pandora {+pandora}"      # new terms go before the sub-sections


def test_frontmatter_keys_and_options(tmp_path, capsys):
    o = outline(capsys, make(tmp_path, {"g/g.game": GAME}), "g/g.game")
    fm = o["frontmatter"]
    assert (fm["start"], fm["end"]) == (1, 10)
    assert [k["key"] for k in fm["keys"] if k["level"] == "top"] == ["title", "players", "values", "symbols", "extensions"]
    assert [(k["key"], k["option"]) for k in fm["keys"] if k["level"] == "option"] == [("description", "pandora"),
                                                                                       ("year", "pandora")]
    assert fm["options"] == [{"name": "pandora", "line": 8, "end": 10, "indent": 2, "kind": "extensions"}]


def test_fragments_and_the_default_language_file(tmp_path, capsys):
    root = make(tmp_path, {"g/g.game": GAME, "_shared/deck.game": "# Glossaire\n\nCarte\n: Une carte.\n",
                           "_shared/deck.en.game": "# Glossary\n\nCard\n: A card.\n",
                           "g/g.en.game": "---\ntitle: G\n---\n# Rules\n\n![[deck#Glossary]]\n\nSee the [[Pion]].\n"})
    o = outline(capsys, root, "g/g.game")
    assert o["includes"][0]["name"] == "deck" and o["includes"][0]["preview"] == "Carte\n: Une carte."
    assert o["fragments"][0]["definitions"][0]["term"] == "Carte"
    en = outline(capsys, root, "g/g.en.game")
    assert en["includes"][0]["file"].endswith("deck.en.game") and en["includes"][0]["section_line"] == 0
    assert en["default"]["file"].endswith("g.game")
    assert "Dé" in [d["term"] for d in en["default"]["definitions"]]


def test_unsaved_text_and_files_outside_the_vault(tmp_path, capsys, monkeypatch):
    root = make(tmp_path, {"g/g.game": GAME})
    o = outline(capsys, root, "g/g.game", stdin="# Only\n\n![x](../../secret.png) [[a]]\n", monkeypatch=monkeypatch)
    assert [h["title"] for h in o["headings"]] == ["Only"]
    assert o["links"][0]["outside"] is True and "path" not in o["links"][0]
    new = outline(capsys, root, "g/new.game", stdin="# New\n", monkeypatch=monkeypatch)     # not saved yet
    assert new["headings"][0]["title"] == "New" and new["vault"] == str(root.resolve())


def test_readable_outline(tmp_path, capsys):
    root = make(tmp_path, {"g/g.game": GAME})
    assert tabula.main(["--vault", str(root), "outline", str(root / "g/g.game")]) == 0
    out = capsys.readouterr().out
    assert "Matériel #components" in out and "  Pandora  {+pandora}" in out and "4 definition(s)" in out
