"""check: a group's count in the components against the counts of the cards it lists."""
import tabula

GAME = """---
title: K
players: 2-5
extensions: [barking]
---
# Matériel {#components}

- 10x [[Attaque]]
  - 5x [[Attaque 2x]]
  - 5x [[Attaque Ciblée 2x]]
- {+barking} 3x [[Attaque Personnelle 3x]]
- 4x [[Passe-Tour]]

# Glossaire {#glossary}

Attaque
: avec::
  Toutes les attaques.
  - [[Attaque 2x]]
  - [[Attaque Ciblée 2x]]
  - {+barking} [[Attaque Personnelle 3x]]

Attaque 2x
: avec:: 2
  Texte.

Attaque Ciblée 2x
: avec:: 2
  Texte.

Attaque Personnelle 3x
: avec:: 1
  Texte.

Passe-Tour
: avec:: 4
  Texte.
"""


def check(tmp_path, capsys, game):
    (tmp_path / "k").mkdir(exist_ok=True)
    (tmp_path / "k" / "k.game").write_text(game, encoding="utf-8")
    tabula.main(["--vault", str(tmp_path), "check", "--no-color"])
    return capsys.readouterr().out


def test_extension_cards_not_counted_in_the_group(tmp_path, capsys):
    out = check(tmp_path, capsys, GAME)
    assert ("k/k.game:16  'Attaque': 10 in the components with every extension and variant, but the cards it lists add up to 13 "
            "(Attaque 2x 5 + Attaque Ciblée 2x 5 + Attaque Personnelle 3x 3)") in out
    assert out.count("'Attaque': 10 in") == 1                       # once, not for each selection


def test_counts_that_match(tmp_path, capsys):
    good = GAME.replace("- {+barking} 3x [[Attaque Personnelle 3x]]", "  - {+barking} 3x [[Attaque Personnelle 3x]]") \
               .replace("- 10x [[Attaque]]", "- {-barking} 10x [[Attaque]]\n- {+barking} 13x [[Attaque]]")
    assert "in the components" not in check(tmp_path, capsys, good)


def test_in_the_base_game(tmp_path, capsys):
    out = check(tmp_path, capsys, GAME.replace("  - 5x [[Attaque Ciblée 2x]]", "  - 4x [[Attaque Ciblée 2x]]"))
    assert "'Attaque': 10 in the components, but the cards it lists add up to 9" in out


def test_no_count_no_check(tmp_path, capsys):
    out = check(tmp_path, capsys, GAME.replace("- 10x [[Attaque]]\n", "").replace("  - 5x [[Attaque", "- 5x [[Attaque"))
    assert "in the components" not in out


def test_listed_cards_without_a_definition_still_count(tmp_path, capsys):
    undefined = GAME.replace("Attaque Personnelle 3x\n: avec:: 1\n  Texte.\n\n", "")
    out = check(tmp_path, capsys, undefined)
    assert "add up to 13 (Attaque 2x 5 + Attaque Ciblée 2x 5 + Attaque Personnelle 3x 3)" in out
    good = undefined.replace("- {+barking} 3x [[Attaque Personnelle 3x]]", "  - {+barking} 3x [[Attaque Personnelle 3x]]") \
                    .replace("- 10x [[Attaque]]", "- {-barking} 10x [[Attaque]]\n- {+barking} 13x [[Attaque]]")
    assert "in the components" not in check(tmp_path, capsys, good)
