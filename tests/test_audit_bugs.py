"""Bugs found by the audits: included sections' conditions, duplicate names, bad vault.yaml, huge player counts,
comments and code blocks, empty values, short plurals, accents, wish remove, sheets."""
import json

import pytest

import tabula


def make(tmp_path, files):
    root = tmp_path / "v"
    for name, text in files.items():
        (root / name).parent.mkdir(parents=True, exist_ok=True)
        (root / name).write_text(text, encoding="utf-8")
    return root


def run(capsys, root, *args):
    code = tabula.main(["--vault", str(root), *args])
    o = capsys.readouterr()
    return code, o.out, o.err


GAME = "---\ntitle: G\nplayers: 2\nvariants: [jokers]\n---\n"


def test_an_included_section_keeps_its_condition(tmp_path, capsys):
    root = make(tmp_path, {
        "_shared/deck.game": "# Matériel\n\n- 52x [[carte]]\n\n## Jokers {+jokers}\n\n- 2x [[joker]]\n\n"
                             "### Règle\n\nLes JOKERS remplacent tout.\n",
        "g/g.game": GAME + "# Matériel {#components}\n\n![[deck#Jokers]]\n\n- 1x [[pion]]\n\n# Jeu\n\nJouez.\n"})
    _, out, _ = run(capsys, root, "show", "g", "--no-color")
    assert "2x joker" not in out and "JOKERS" not in out and "pion" in out and "Jouez" in out
    _, out, _ = run(capsys, root, "show", "g", "-v", "jokers", "--no-color")
    assert "2x joker" in out and "JOKERS remplacent" in out and "pion" in out
    _, out, _ = run(capsys, root, "export", "g", "--interactive", "-o", "-")
    assert out.count("&quot;jokers&quot;") >= 2              # the page can hide them when jokers is off
    assert "\x00" not in out and "scope" not in out.split("<main>")[1].split("</main>")[0].replace('class="scope"', "")
    _, out, _ = run(capsys, root, "check", "--no-color")
    assert "0 error(s), 0 warning(s)" in out


def test_two_games_with_one_name(tmp_path, capsys):
    root = make(tmp_path, {"x.game": GAME + "# A\n\nA.\n", "x/x.game": GAME + "# B\n\nB.\n"})
    code, _, _ = run(capsys, root, "site", "-o", str(tmp_path / "site"))
    assert code == 0 and (tmp_path / "site" / "x" / "index.html").is_file()
    _, out, _ = run(capsys, root, "check", "--no-color")
    assert out.count("two games named 'x'") == 1


def test_vault_yaml_that_isnt_settings(tmp_path, capsys):
    root = make(tmp_path, {"vault.yaml": "- a\n- b\n", "g/g.game": GAME + "# A\n\nA.\n"})
    code, out, _ = run(capsys, root, "check", "--no-color")
    assert code == 1 and "vault.yaml must be settings" in out
    assert run(capsys, root, "show", "g", "--no-color")[0] == 0


def test_huge_player_counts_dont_hang(tmp_path, capsys):
    root = make(tmp_path, {"g/g.game": "---\ntitle: G\nplayers: 2-99999999\n---\n# A\n\nA.\n"})
    assert run(capsys, root, "export", "g", "--interactive", "-o", "-")[0] == 0
    assert run(capsys, root, "site", "-o", str(tmp_path / "site"))[0] == 0
    assert "more than 100 players" in run(capsys, root, "check", "--no-color")[1]


def test_comments_in_code_and_unclosed_code_blocks(tmp_path, capsys):
    body = "# A\n\n```\n<!-- not a comment\n```\n\nVisible `<!--` text.\n\n<!-- hidden -->Shown.\n\n# B\n\nAfter.\n"
    root = make(tmp_path, {"g/g.game": GAME + body})
    _, out, _ = run(capsys, root, "show", "g", "--no-color")
    assert "<!-- not a comment" in out and "After." in out and "Shown." in out and "hidden" not in out
    _, out, _ = run(capsys, root, "check", "--no-color")
    assert "unclosed comment" not in out
    root = make(tmp_path / "2", {"g/g.game": GAME + "# A\n\n```\ncode\n\n# B\n\nText.\n"})
    assert "code block opened here is never closed" in run(capsys, root, "check", "--no-color")[1]


def test_frontmatter_can_end_with_dots(tmp_path, capsys):
    root = make(tmp_path, {"g/g.game": "---\ntitle: Dots\nplayers: 2\n...\n# A\n\nA.\n"})
    _, out, _ = run(capsys, root, "show", "g", "--no-color")
    assert out.startswith("Dots")


def test_empty_values(tmp_path, capsys):
    root = make(tmp_path, {"g/g.game": "---\ntitle: G\nplayers: 2\nvalues:\n  main:\n  hand: {2p: , \"*\": 5}\n---\n"
                                       "# A\n\nDeal {=main} cards, then {=hand}.\n"})
    _, out, _ = run(capsys, root, "show", "g", "--no-color")
    assert "None" not in out
    _, out, _ = run(capsys, root, "check", "--no-color")
    assert "value 'main' is empty" in out and "'2p' has no value" in out


def test_short_plurals_and_accents_match(tmp_path, capsys):
    body = ("# Matériel {#components}\n\n- 2x [[dé]]\n- 1x [[Évènement]]\n\n# Jeu\n\nLancez les [[dés]], lisez "
            "l'[[evenement]].\n\n# Glossaire {#glossary}\n\nDé\n: Un cube.\n\nÉvènement\n: Une carte.\n")
    root = make(tmp_path, {"g/g.game": GAME + body})
    _, out, _ = run(capsys, root, "check", "--no-color")
    assert "matches nothing" not in out and "0 warning(s)" in out, out


def test_wish_remove_leaves_no_dash(tmp_path, capsys):
    root = make(tmp_path, {"g/g.game": GAME + "# A\n\nA.\n",
                           "wishlist.yaml": "-\n  name: Alpha\n  priority: 1\n-\n  name: Beta\n"})
    run(capsys, root, "wish", "remove", "Alpha")
    text = (root / "wishlist.yaml").read_text(encoding="utf-8")
    assert text.strip().splitlines()[0] == "-" and "Alpha" not in text and text.count("-\n") == 1


def test_check_a_missing_sheet(tmp_path, capsys):
    root = make(tmp_path, {"g/g.game": GAME + "# A\n\nA.\n"})
    with pytest.raises(SystemExit, match="no score sheet"):
        tabula.main(["--vault", str(root), "check", str(root / "g" / "nope.sheet")])


def test_sheets_use_the_vaults_language(tmp_path, capsys):
    root = make(tmp_path, {"vault.yaml": "language: de\n", "g/g.game": "---\ntitle: G\nplayers: 2\n---\n# A\n\nA.\n",
                           "g/g.sheet": "---\nsize: a5\n---\n| Runde | {player} |\n|---|---|\n| {r} | |\n"})
    run(capsys, root, "sheet", "g", "-o", str(tmp_path / "s.html"))
    assert '<html lang="de">' in (tmp_path / "s.html").read_text(encoding="utf-8")


def test_options_after_a_list_of_names(tmp_path, capsys):
    root = make(tmp_path, {"g/g.game": GAME + "# Glossaire {#glossary}\n\nCarte\n: A card.\n"})
    code, out, _ = run(capsys, root, "lookup", "g", "-v", "jokers", "carte", "--no-color")
    assert code == 0 and "A card." in out
