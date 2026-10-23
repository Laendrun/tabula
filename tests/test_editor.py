"""The editor features (editor.py) the language server serves: rename, quick fixes, completion, symbols."""
from pathlib import Path

import pytest

from tabula import editor
from tabula.outline import outline_file
from tabula.vault import open_vault


def outline(tmp_path, text, name="g/g.game", files=None):
    root = tmp_path / "v"
    for n, t in {"vault.yaml": "name: T\n", **(files or {}), name: text}.items():
        (root / n).parent.mkdir(parents=True, exist_ok=True)
        (root / n).write_text(t, encoding="utf-8")
    p = root / name
    return outline_file(p, open_vault(None, str(p)))


def apply(text, edits):
    lines = text.split("\n")
    for e in sorted(edits, key=lambda e: (-e["line"], -e["start"])):
        l = lines[e["line"]] if e["line"] < len(lines) else ""
        lines[e["line"]] = l[:e["start"]] + e["text"] + l[e["end"]:]
    return "\n".join(lines)


GAME = """---
title: G
players: 2
---
# How to play {#play}

Move a [[bateau]], then two [[bateaux]] and a [[Bateau|navire]]. See [[#Tide rules]] and [[#play]].

## Tide rules

Every [[Bateau]] floats. `[[Bateau]]` in code stays.

# Glossary {#glossary}

Bateau {2p}
: A boat.

## Cards {#cards}

Gust
: effect:: wind
"""


def test_rename_a_term_keeps_case_plurals_aliases(tmp_path):
    o = outline(tmp_path, GAME)
    col = GAME.split("\n")[6].index("bateau]]") + 2
    assert editor.rename_target(o, 6, col)["placeholder"] == "Bateau"
    out = apply(GAME, editor.rename_edits(o, 6, col, "Navire"))
    assert "Move a [[navire]], then two [[Navire|bateaux]] and a [[Navire|navire]]" in out
    assert "Every [[Navire]] floats. `[[Bateau]]` in code stays." in out
    assert "\nNavire {2p}\n: A boat." in out
    assert "\nBoat {2p}\n" in apply(GAME, editor.rename_edits(o, 14, 0, "Boat"))


def test_rename_a_heading_not_role_links(tmp_path):
    o = outline(tmp_path, GAME)
    out = apply(GAME, editor.rename_edits(o, 8, 4, "Tides"))
    assert "## Tides\n" in out and "See [[#Tides]] and [[#play]]" in out
    with pytest.raises(editor.RenameError, match="links to a role"):
        editor.rename_target(o, 6, GAME.split("\n")[6].index("#play") + 1)
    with pytest.raises(editor.RenameError, match="can't be empty"):
        editor.rename_edits(o, 14, 0, "a|b")
    with pytest.raises(editor.RenameError, match="Put the cursor"):
        editor.rename_edits(o, 7, 0, "X")


def test_quick_fixes(tmp_path):
    f = editor.quick_fixes(["Le délenche."], {}, 0, "unknown word 'délenche' (did you mean 'déclenche'?)", 3, 11)
    assert [x["title"] for x in f] == ["Change to 'déclenche'", "Add 'délenche' to words.txt"]
    assert apply("Le délenche.", f[0]["edits"]) == "Le déclenche."
    fm = ["---", "title: G", "durantion: 10", "---"]
    f = editor.quick_fixes(fm, {}, 0, "'durantion:' in frontmatter: did you mean 'duration'? (other keys…)", 0, 3)
    assert apply("\n".join(fm), f[0]["edits"]).split("\n")[2] == "duration: 10"
    text = "# Play\n\nDraw a [[Grnde marée|big one]].\n\n# Glossaire {#glossary}\n\nGrande marée\n: Tide.\n\n## Cartes {#cards}\n"
    o = outline(tmp_path, text)
    msg = "[[Grnde marée|big one]] matches no component ('- 1x [[Grnde marée]]' in a list) and no definition"
    f = editor.quick_fixes(text.split("\n"), o, 2, msg, 7, 30)
    assert [x["title"] for x in f] == ["Change to [[Grande marée]]", "Define 'Grnde marée' in the glossary"]
    assert "Draw a [[Grande marée|big one]]." in apply(text, f[0]["edits"])
    assert ": Tide.\n\nGrnde marée\n: \n\n## Cartes" in apply(text, f[1]["edits"])


def test_completion_items(tmp_path):
    text = "---\ntitle: G\nplayers: 2\n---\n# R {#play}\n\nVoir [[\n\n# G {#glossary}\n\nCarte\n: Une carte.\n"
    o = outline(tmp_path, text, files={"_shared/deck.game": "# Kit\n"})
    items = editor.completion(o, "Voir [[", 6, 7, Path("g.game"), Path(o["vault"]))
    assert [(i["label"], i["insert"], i["start"], i["end"]) for i in items] == [("Carte", "Carte]]", 7, 7)]
    frag = editor.completion(o, "![[de", 6, 5, Path("g.game"), Path(o["vault"]))
    assert [i["label"] for i in frag] == ["deck"]
    o2 = outline(tmp_path / "2", text.replace("players: 2\n", "players: 2\npl\n"))
    keys = editor.completion(o2, "pl", 3, 2, Path("g.game"), Path(o2["vault"]))
    assert "year" in [i["label"] for i in keys] and "players" not in [i["label"] for i in keys]   # already there


def test_symbols_and_issue_columns(tmp_path):
    o = outline(tmp_path, GAME)
    s = editor.symbols(o)
    assert [x["name"] for x in s] == ["How to play", "Glossary"]
    assert [x["name"] for x in s[1]["children"]] == ["Bateau", "Cards"]
    assert editor.issue_columns("Voir [[crad]] ici", "[[crad]] matches nothing") == (5, 13)
    assert editor.issue_columns("Une cartes et carte", "unknown word 'carte'") == (14, 19)
    assert editor.issue_columns("  Texte", "x") == (2, 7)


def test_schemas_are_those_of_the_spec():
    spec = Path(__file__).resolve().parents[1] / "spec" / "schemas"
    for f in spec.glob("*.json"):
        assert (editor.SCHEMA_DIR / f.name).read_text(encoding="utf-8") == f.read_text(encoding="utf-8"), \
            f"copy spec/schemas/{f.name} to cli/tabula/schemas/"
