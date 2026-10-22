"""Totals: an empty field in a definition that lists cards is the sum of theirs."""
import json

import tabula

GAME = """---
title: K
players: 2-5
extensions: [barking, zombie]
---
# Glossaire {#glossary}

Attaque
: avec::
  sans::
  type::
  Toutes les cartes de type Attaque
  - [[Attaque 2x]]
  - [[Attaque Ciblée 2x|ciblée]]
  - {+barking} [[Attaque Personnelle 3x]]
  - [[Attaque des morts]]

Tout
: avec::
  - [[Attaque]]
  - [[Passe-Tour]]

Attaque 2x
: avec:: 2
  sans:: 3
  type:: attaque
  Ne piochez aucune carte.

Attaque Ciblée 2x
: avec:: 2
  sans:: 3
  type:: ciblée
  Forcez n'importe quel joueur.

Passe-Tour
: avec:: 4
  Terminez votre tour.

## Barking {+barking}

Attaque Personnelle 3x
: avec:: 1
  sans:: 1
  Jouez 3 tours.

## Zombie {+zombie}

Attaque des morts
: avec:: 2.5
  Les morts attaquent.
"""


def vault(tmp_path, game=GAME):
    (tmp_path / "k").mkdir(exist_ok=True)
    (tmp_path / "k" / "k.game").write_text(game, encoding="utf-8")
    return tmp_path


def run(capsys, v, *args):
    code = tabula.main(["--vault", str(v), *args])
    return code, capsys.readouterr().out


def fields(capsys, v, *args):
    _, out = run(capsys, v, "show", "k", "--json", *args)
    return {b["term"]: b.get("fields") for b in json.loads(out)["blocks"] if b.get("term") in ("Attaque", "Tout")}


def test_totals_follow_the_selection(tmp_path, capsys):
    v = vault(tmp_path)
    assert fields(capsys, v)["Attaque"] == {"avec": "4", "sans": "6", "type": "attaque, ciblée"}
    assert fields(capsys, v, "-e", "barking")["Attaque"]["avec"] == "5"
    got = fields(capsys, v, "--all")
    assert got["Attaque"]["avec"] == "7.5" and got["Attaque"]["sans"] == "7"
    assert got["Tout"] == {"avec": "11.5"}                                  # a group of groups


def test_lookup(tmp_path, capsys):
    _, out = run(capsys, vault(tmp_path), "lookup", "k", "attaque", "-e", "barking", "--no-color")
    assert "avec: 5" in out and "sans: 7" in out


def test_cards_nests_groups(tmp_path, capsys):
    v = vault(tmp_path)
    _, out = run(capsys, v, "cards", "k", "--json")
    rows = json.loads(out)
    assert [(r["card"], r["kind"]) for r in rows][:4] == [("Tout", "group"), ("Attaque", "group"),
                                                         ("Attaque 2x", "card"), ("Attaque Ciblée 2x", "card")]
    assert rows[1]["cards"] == ["Attaque 2x", "Attaque Ciblée 2x"] and rows[1]["avec"] == "4"
    _, out = run(capsys, v, "cards", "k", "--no-color")
    lines = out.splitlines()
    assert lines[1].startswith("Tout Σ") and lines[2].startswith("  Attaque Σ")
    assert lines[3].startswith("    Attaque 2x") and lines[5].startswith("  Passe-Tour")
    assert "3 cards · 2 groups" in out
    _, out = run(capsys, v, "cards", "k", "--no-color", "--sort", "avec")
    assert [l.split()[0] for l in out.splitlines()[1:6]] == ["Attaque", "Attaque", "Passe-Tour", "Tout", "Attaque"]
    v = vault(tmp_path, GAME.replace("# Glossaire {#glossary}\n", "# Glossaire {#glossary}\n\n## Cartes {#cards}\n"))
    _, out = run(capsys, v, "export", "k", "-o", "-")
    assert '<tr class="group"><td><a class="ref" href="#t-tout">Tout</a> <span class="sigma"' in out


def test_interactive_page(tmp_path, capsys):
    _, out = run(capsys, vault(tmp_path), "export", "k", "--interactive", "-o", "-")
    assert '<i class="total" data-counts=\'[[[],2],[[],2],[[[&quot;v&quot;,false,&quot;barking&quot;]],1],' \
           '[[[&quot;v&quot;,false,&quot;zombie&quot;]],2.5]]\'>7.5</i>' in out
    _, out = run(capsys, vault(tmp_path), "export", "k", "-o", "-")
    assert 'class="total"' not in out and "<span>avec</span> 4</li>" in out


def test_check(tmp_path, capsys):
    code, out = run(capsys, vault(tmp_path), "check", "--no-color")
    assert code == 0 and "is empty" not in out, out
    bad = GAME.replace("  type::\n", "  couleur::\n").replace("Passe-Tour\n: avec:: 4", "Passe-Tour\n: avec:: 4\n  rien::")
    _, out = run(capsys, vault(tmp_path, bad), "check", "--no-color")
    assert "field 'couleur' of 'Attaque' is empty, and none of the cards it lists has a 'couleur' to add up" in out
    assert "field 'rien' of 'Passe-Tour' is empty (an empty field is a total" in out
