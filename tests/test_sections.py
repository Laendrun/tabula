"""`---` alone on a line ends the current section: what follows belongs to the section around it."""
import json

import tabula

BODY = """# Glossary {#glossary}

## Playing cards {#cards}

Red
: points:: 1
  RED-TEXT

Blue
: points:: 2
  BLUE-TEXT

---

Effect
: EFFECT-TEXT

## Two players {2p}

PAIR text

---

BACK-HOME text
"""


def game(tmp_path, body=BODY):
    (tmp_path / "g").mkdir(exist_ok=True)
    (tmp_path / "g" / "g.game").write_text(f"---\ntitle: G\nplayers: 2-4\n---\n{body}", encoding="utf-8")
    return tmp_path


def run(capsys, vault, cmd, *args):
    extra = ["--no-color"] if cmd in ("show", "lookup", "cards") else ["-o", "-"]
    code = tabula.main(["--vault", str(vault), cmd, "g", *extra, *args])
    return code, capsys.readouterr().out


def test_terms_after_the_end_are_not_cards(tmp_path, capsys):
    _, out = run(capsys, game(tmp_path), "cards")
    assert "Red" in out and "Blue" in out and "Effect" not in out


def test_the_condition_of_a_closed_section_stops_applying(tmp_path, capsys):
    vault = game(tmp_path)
    _, out = run(capsys, vault, "show", "-p", "3")
    assert "PAIR" not in out and "BACK-HOME" in out
    _, out = run(capsys, vault, "show", "-p", "2")
    assert "PAIR" in out and "BACK-HOME" in out


def test_end_marker_is_shown_only_when_it_closes_something(tmp_path, capsys):
    vault = game(tmp_path)
    _, out = run(capsys, vault, "show", "-p", "2")
    assert out.count("· · ·") == 2
    _, out = run(capsys, vault, "show", "-p", "3")       # the 2p section is hidden: nothing to close there
    assert out.count("· · ·") == 1


def test_end_marker_is_not_glued_to_a_paragraph(tmp_path, capsys):
    vault = game(tmp_path, "# Setup\n\n## Sub\n\nSUB text\n---\nBACK text\n")
    _, out = run(capsys, vault, "show")
    assert "---" not in out and "SUB text\n" in out


def test_reopened_cards_section_is_one_catalog(tmp_path, capsys):
    body = ("# Cards {#cards}\n\nAce\n: points:: 1\n\n## Specials\n\nJoker\n: points:: 9\n\n---\n\n"
            "King\n: points:: 4\n")
    vault = game(tmp_path, body)
    _, out = run(capsys, vault, "cards", "--json")
    groups = {c["card"]: c["group"] for c in json.loads(out)}
    assert groups == {"Ace": "Cards", "Joker": "Specials", "King": "Cards"}
    _, html = run(capsys, vault, "export")
    assert html.count('<table class="catalog') == 1 and html.count('<hr class="end">') == 1
    table = html[html.index('<table class="catalog'):html.index("</table>")]
    assert "Ace" in table and "Joker" in table and "King" in table


def test_section_selection_stops_at_the_end(tmp_path, capsys):
    _, out = run(capsys, game(tmp_path), "show", "-s", "playing cards")
    assert "RED-TEXT" in out and "EFFECT-TEXT" not in out


def test_json_and_check(tmp_path, capsys):
    vault = game(tmp_path)
    _, out = run(capsys, vault, "show", "--json", "-p", "2")
    assert '"kind": "end"' in out
    assert tabula.main(["--vault", str(vault), "check", "--no-color"]) == 0
