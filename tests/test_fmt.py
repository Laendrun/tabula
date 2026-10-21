"""`tabula fmt`: tidy files without changing what they say; and | inside [[a|b]] in tables and choices."""
import io
import sys

import pytest

import tabula
from conftest import EXAMPLES, FIXTURES
from tabula.fmt import format_game, format_text

MESSY = """---
title: G
players: 2-4
---
# Rules
Text right under the heading.


## Two players {2p}
- a list item
| Card | Effect |
|---|:---:|
| [[Deck|the deck]] | shuffle |
| Joker \\| wild | any |
---
After the end.
```
  keep   this
| not | a | table |


```
<!-- a comment

   with blank lines   -->
# Glossary
Deck
: Cards.


"""

TIDY = """---
title: G
players: 2-4
---

# Rules

Text right under the heading.

## Two players {2p}

- a list item
| Card              | Effect  |
|-------------------|:-------:|
| [[Deck|the deck]] | shuffle |
| Joker \\| wild     | any     |

---

After the end.
```
  keep   this
| not | a | table |


```
<!-- a comment

   with blank lines   -->

# Glossary

Deck
: Cards.
"""


def test_format_text():
    assert format_text(MESSY) == TIDY
    assert format_text(TIDY) == TIDY                                     # formatting twice changes nothing


def test_keeps_windows_line_endings_and_table_style():
    crlf = TIDY.replace("\n", "\r\n")
    assert format_text(crlf) == crlf
    spaced = "# T\n\n| a | bb |\n| --- | :-: |\n| ccc | d |\n"
    assert format_text(spaced) == "# T\n\n| a   | bb  |\n| --- | :-: |\n| ccc | d   |\n"


def test_wide_and_accented_characters_align():
    out = format_text("| Blason | X |\n|-|-|\n| Érudit | 1 |\n| 城 | 2 |\n")
    assert out.splitlines()[1] == "|--------|---|"
    assert out.splitlines()[2] == "| Érudit | 1 |" and out.splitlines()[3] == "| 城     | 2 |"


def test_never_changes_what_a_game_says(tmp_path, monkeypatch):
    p = tmp_path / "g.game"
    p.write_text("x", encoding="utf-8")
    text = "# Rules\n\nDeck\n: one\n\n\n  two\n"            # two blank lines end the definition…
    monkeypatch.setattr("tabula.fmt.format_text", lambda t: "# Rules\n\nDeck\n: one\n\n  two\n")   # …one doesn't
    new, safe = format_game(p, text)
    assert not safe


@pytest.mark.parametrize("vault", [EXAMPLES, FIXTURES], ids=["examples", "fixtures"])
def test_vaults_are_formatted_safely(vault, tmp_path, capsys):
    import shutil
    shutil.copytree(vault, tmp_path / "v")
    code = tabula.main(["--vault", str(tmp_path / "v"), "fmt"])
    out = capsys.readouterr().out
    assert code == 0 and "left as they are" not in out
    assert tabula.main(["--vault", str(tmp_path / "v"), "fmt", "--check"]) == 0          # nothing left to do
    assert "0 would be formatted" in capsys.readouterr().out


def test_check_and_stdin(tmp_path, capsys, monkeypatch):
    (tmp_path / "g").mkdir()
    f = tmp_path / "g" / "g.game"
    f.write_text(MESSY, encoding="utf-8")
    (tmp_path / "g" / "g.fr.game").write_text("---\ntitle: G\n---\n# Règles\nTexte.\n", encoding="utf-8")
    assert tabula.main(["--vault", str(tmp_path), "fmt", "g", "--check"]) == 1
    out = capsys.readouterr().out
    assert "would format: g/g.game" in out and "would format: g/g.fr.game" in out
    assert f.read_text(encoding="utf-8") == MESSY                          # --check writes nothing
    monkeypatch.setattr(sys, "stdin", io.TextIOWrapper(io.BytesIO(MESSY.encode())))
    assert tabula.main(["fmt", str(f), "--stdin"]) == 0
    assert capsys.readouterr().out == TIDY
    assert tabula.main(["--vault", str(tmp_path), "fmt", "g"]) == 0
    assert f.read_text(encoding="utf-8") == TIDY


def test_pipes_in_references_inside_tables_and_choices(tmp_path, capsys):
    (tmp_path / "g").mkdir()
    (tmp_path / "g" / "g.game").write_text(
        "---\ntitle: G\nplayers: 2-4\n---\n# Rules\n\n| Card | Effect |\n|---|---|\n| [[Deck|the deck]] | a \\| b |\n\n"
        "Deal {2p: [[Deck|the deck]] | *: half}.\n\n# Glossary\n\nDeck\n: Cards.\n", encoding="utf-8")
    tabula.main(["--vault", str(tmp_path), "show", "g", "-p", "2", "--no-color"])
    out = capsys.readouterr().out
    assert "the deck  a | b" in out and "Deal the deck." in out
    assert tabula.main(["--vault", str(tmp_path), "check", "--no-color"]) == 0
    assert "0 error(s), 0 warning(s)" in capsys.readouterr().out
