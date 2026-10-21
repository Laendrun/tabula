"""Values: defined once in vault.yaml or the frontmatter, written {=name}."""
import json

import tabula


def vault(tmp_path, body, meta="", config='language: en\nvalues:\n  target: 100\n  hand: {2p: 9, "*": 5}\n', extra=None):
    root = tmp_path / "v"
    (root / "g").mkdir(parents=True, exist_ok=True)
    (root / "vault.yaml").write_text(config, encoding="utf-8")
    (root / "g" / "g.game").write_text(f"---\ntitle: G\nplayers: 2-4\nvariants: [quick]\n{meta}---\n{body}", encoding="utf-8")
    for name, text in (extra or {}).items():
        (root / name).parent.mkdir(parents=True, exist_ok=True)
        (root / name).write_text(text, encoding="utf-8")
    return root


def show(capsys, root, *args):
    code = tabula.main(["--vault", str(root), "show", "g", "--no-color", *args])
    return code, capsys.readouterr().out


def check(capsys, root):
    code = tabula.main(["--vault", str(root), "check", "--no-color"])
    return code, capsys.readouterr().out


GAME_VALUES = 'values:\n  hand: {2p: 7, 3p: 6, "*": 5}\n  speed: {+quick: fast, "*": slow}\n'


def test_values_by_player_count_and_option(tmp_path, capsys):
    root = vault(tmp_path, "# Setup\n\nDeal {=hand} cards, play to {=target}, {=speed}. `{=hand}` stays.\n", GAME_VALUES)
    assert "Deal 7 cards, play to 100, slow." in show(capsys, root, "-p", "2")[1]   # the game's hand wins
    assert "Deal 6 cards" in show(capsys, root, "-p", "3")[1]
    assert "Deal 5 cards" in show(capsys, root, "-p", "4", "-v", "quick")[1]
    assert "fast" in show(capsys, root, "-p", "4", "-v", "quick")[1]
    assert "`{=hand}` stays" in show(capsys, root, "-p", "2")[1]   # in code: as written
    out = show(capsys, root)[1]
    assert "⟨2p: 7 | 3p: 6 | *: 5⟩" in out                      # no player count chosen: every case


def test_vault_values_alone(tmp_path, capsys):
    root = vault(tmp_path, "# Setup\n\nDeal {=hand}.\n")
    assert "Deal 9." in show(capsys, root, "-p", "2")[1] and "Deal 5." in show(capsys, root, "-p", "3")[1]


def test_player_table_cells_resolve_per_column(tmp_path, capsys):
    body = "# Setup\n\n| Hand | 2p | 3p | 4p |\n|---|---|---|---|\n| Cards | {=hand} | {=hand} | {=hand} |\n" \
           "| Goal | {=target} | {2p: a | *: b} | {+quick: q | *: n} |\n"
    out = show(capsys, vault(tmp_path, body, GAME_VALUES))[1]
    assert "Cards  7    6   5" in out                            # each column: its own player count
    assert "Goal   100  b   n" in out                            # option choices follow -v as usual


def test_site_page_gets_a_choice(tmp_path, capsys):
    root = vault(tmp_path, "# Setup\n\nDeal {=hand} cards.\n", GAME_VALUES)
    tabula.main(["--vault", str(root), "export", "g", "--interactive", "-o", "-"])
    html = capsys.readouterr().out
    assert 'class="choice" data-choice' in html and "7" in html


def test_translation_values(tmp_path, capsys):
    root = vault(tmp_path, "# Setup\n\nPlay {=speed}.\n", GAME_VALUES,
                 extra={"g/g.fr.game": '---\ntitle: G\nvalues:\n  speed: {+quick: vite, "*": lentement}\n---\n'
                                       "# Mise en place\n\nJouez {=speed}, {=hand} cartes.\n"})
    _, out = show(capsys, root, "-l", "fr", "-p", "2")
    assert "Jouez lentement, 7 cartes." in out


def test_check(tmp_path, capsys):
    root = vault(tmp_path, "# Setup\n\nDeal {=hnad} and {=nothing}.\n",
                 'values:\n  hand: 5\n  bad: {4x: 1}\n  list: [1, 2]\n',
                 config="language: en\nvalues:\n  oops: {2p: 1, 3q: 2}\n")
    code, out = check(capsys, root)
    assert code == 1
    assert "vault.yaml:1  value 'oops': '3q' is not a condition" in out
    assert "g/g.game:1  value 'bad': '4x' is not a condition" in out
    assert "value 'list' is a list" in out
    assert "g/g.game:12  unknown value '{=hnad}' (did you mean 'hand'?)" in out
    assert "unknown value '{=nothing}' (define it under 'values:'" in out


def test_fragments_use_the_games_values(tmp_path, capsys):
    root = vault(tmp_path, "# Setup\n\n![[deal]]\n", GAME_VALUES,
                 extra={"_shared/deal.game": "# Deal\n\nDeal {=hand} cards.\n"})
    assert "Deal 7 cards." in show(capsys, root, "-p", "2")[1]
    code, out = check(capsys, root)
    assert code == 0, out                          # the fragment alone doesn't know 'hand': not an error there


def test_json_and_spelling_untouched(tmp_path, capsys):
    root = vault(tmp_path, "# Setup\n\nDeal {=hand}.\n", GAME_VALUES)
    _, out = show(capsys, root, "-p", "3", "--json")
    assert "Deal 6." in json.dumps(json.loads(out))
