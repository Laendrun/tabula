"""Card catalog: `key:: value` fields, counts from the component list, `tabula cards`, display everywhere."""
import json

import pytest

import tabula
from conftest import FIXTURES


@pytest.fixture
def cli(capsys):
    def run(cmd, *args, vault=FIXTURES, game="kitchen-sink"):
        extra = ["--no-color"] if cmd in ("show", "lookup", "cards") else ["-o", "-"]
        code = tabula.main(["--vault", str(vault), cmd, game, *extra, *args])
        out = capsys.readouterr()
        return code, out.out, out.err
    return run


def game(tmp_path, body, meta="title: G\nplayers: 2-4"):
    (tmp_path / "g").mkdir(exist_ok=True)
    (tmp_path / "g" / "g.game").write_text(f"---\n{meta}\n---\n{body}", encoding="utf-8")
    return tmp_path


def test_fields_are_parsed():
    vault = tabula.Vault(FIXTURES)
    g = vault.load(vault.find("kitchen-sink"))
    rocket = next(e for e in tabula.lookup_entries(g.blocks) if e.name == "Rocket").blocks[0]
    assert rocket.fields == {"points": "5", "timing": "1st"}
    assert rocket.children[0].text == "ZULU rocket text."           # fields are not part of the text


def test_cards_table_with_counts_from_components(cli):
    code, out, _ = cli("cards", "-e", "expo")
    assert code == 0
    lines = {l.split()[0]: l.split() for l in out.splitlines() if l.startswith(("Rocket", "Comet"))}
    assert lines["Rocket"][:4] == ["Rocket", "4", "5", "1st"]       # 4 from "- 4x [[rocket]]"
    assert lines["Comet"][:4] == ["Comet", "6", "3", "2nd"]
    assert "Expo cards" in out and "2 cards" in out


def test_cards_respect_the_selection(cli):
    code, _, err = cli("cards")                                     # base game: no expansion cards
    assert code == 1 and "try --all" in err
    code, out, _ = cli("cards", "--all")
    assert code == 0 and "+expo" in out


def test_sort_and_json(cli):
    _, out, _ = cli("cards", "-e", "expo", "--sort", "points")
    names = [l.split()[0] for l in out.splitlines() if l.startswith(("Rocket", "Comet"))]
    assert names == ["Comet", "Rocket"]
    _, out, _ = cli("cards", "-e", "expo", "--json")
    rows = {r["card"]: r for r in json.loads(out)}
    assert rows["Rocket"] == {"card": "Rocket", "count": "4", "points": "5", "timing": "1st",
                              "ext": "+expo", "group": "Expo cards", "kind": "card"}
    code, _, err = cli("cards", "-e", "expo", "--sort", "nope")
    assert code == 2 and "columns" in err


def test_fields_in_show_lookup_and_export(cli):
    assert "points: 5" in cli("show", "-e", "expo")[1]
    assert "timing: 1st" in cli("lookup", "rocket")[1]
    _, out, _ = cli("export", "-e", "expo")
    assert '<ul class="fields"><li><span>points</span> 5</li>' in out
    assert '<table class="catalog">' in out and "<th>count</th>" in out


def test_component_lines_may_have_words_before_the_reference(tmp_path, capsys):
    v = game(tmp_path, "# Matériel\n\n- 8x cartes [[Gift]] (2 par couleur)\n- {+x} 2x cartes [[Gift]]\n\n"
                       "# Cartes {#cards}\n\nGift\n: points:: 7\n  Offre deux cartes.\n",
             meta="title: G\nplayers: 2-4\nextensions: [x]")
    tabula.main(["--vault", str(v), "cards", "g", "--no-color"])
    assert "Gift  8" in capsys.readouterr().out
    tabula.main(["--vault", str(v), "cards", "g", "-e", "x", "--no-color"])
    assert "Gift  10" in capsys.readouterr().out


def test_count_field_when_there_is_no_component_list(tmp_path, capsys):
    v = game(tmp_path, "# Cartes {#cards}\n\nJoker\n: count:: 2\n  points:: 50\n  Remplace tout.\n")
    tabula.main(["--vault", str(v), "cards", "g", "--no-color"])
    out = capsys.readouterr().out
    assert "Joker  2" in out and "50" in out


@pytest.mark.parametrize("body, expected", [
    ("Card\n: points::\n  Text.\n", "field 'points' of 'Card' is empty"),
    ("Card\n: points:: 1\n  points:: 2\n  Text.\n", "written twice"),
    ("Card\n: Some text.\n\n  points:: 3\n", "looks like a field but is below the text"),
    ("# C {#cards}\n\nA\n: points:: 1\n  a\n\nB\n: points:: 2\n  b\n\nC\n: c\n",
     "card 'C' has no 'points::' field (2 of 3 cards"),
])
def test_field_problems(check_body, body, expected):
    messages = check_body(body)
    assert any(expected in m for m in messages), messages


def test_no_warning_when_few_cards_have_a_field(check_body):
    body = "# C {#cards}\n\nA\n: points:: 1\n  a\n\nB\n: b\n\nC\n: c\n"
    assert check_body(body) == []


def test_field_that_depends_on_a_variant(tmp_path, capsys):
    v = game(tmp_path, "# Cartes {#cards}\n\nCurse\n: points:: {+points: 13}\n  type:: particulière\n  Injouable.\n",
             meta="title: G\nplayers: 2-4\nvariants: [points]")
    tabula.main(["--vault", str(v), "show", "g", "--no-color"])
    out = capsys.readouterr().out
    assert "points:" not in out and "type: particulière" in out
    tabula.main(["--vault", str(v), "show", "g", "-v", "points", "--no-color"])
    assert "points: 13" in capsys.readouterr().out


MULTILINE = """# Cartes {#cards}

7
: effet:: Remplacez le jeton.
  valeur:: 7

8
: effet:: Vous ne pouvez pas vous défausser d'un 8 s'il
    n'y a pas au moins 6 cartes dans la pile de défausse.
    Terminez immédiatement la manche.
  valeur:: 8
  CARD-TEXT under the fields.

9
: effet:: Une ligne.

    Pas la suite : une ligne vide termine le champ.
"""


def test_field_continues_on_indented_lines(tmp_path, capsys):
    v = game(tmp_path, MULTILINE)
    g = tabula.Vault(v).load(v / "g" / "g.game")
    cards = {e.name: e.blocks[0] for e in tabula.lookup_entries(g.blocks)}
    assert cards["8"].fields == {
        "effet": "Vous ne pouvez pas vous défausser d'un 8 s'il n'y a pas au moins 6 cartes dans la pile de "
                 "défausse. Terminez immédiatement la manche.",
        "valeur": "8"}
    assert [k.text for k in cards["8"].children] == ["CARD-TEXT under the fields."]
    assert cards["9"].fields == {"effet": "Une ligne."}                  # a blank line ends the field
    assert "Pas la suite" in cards["9"].children[0].text
    assert tabula.main(["--vault", str(v), "check", "--no-color"]) == 0


def test_long_fields_are_wrapped_for_reading(tmp_path, capsys, monkeypatch):
    v = game(tmp_path, MULTILINE)
    monkeypatch.setenv("COLUMNS", "70")
    tabula.main(["--vault", str(v), "cards", "g", "--no-color"])
    table = capsys.readouterr().out
    assert all(len(line) <= 70 for line in table.splitlines())          # the table fits the terminal
    assert "Terminez" in table and "8" in table
    tabula.main(["--vault", str(v), "lookup", "g", "8", "--no-color"])
    out = capsys.readouterr().out
    assert "\n    valeur: 8\n" in out                                    # one field per line when they're long
    tabula.main(["--vault", str(v), "lookup", "g", "7", "--no-color"])
    assert "effet: Remplacez le jeton.   valeur: 7" in capsys.readouterr().out   # short ones stay together
