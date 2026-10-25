"""Extension and variant details: players, duration, needs, excludes."""
import json

import tabula

GAME = """---
title: F
players: 2-8
extensions:
  troublemaker: "Troublemaker"
  pandora:
    description: "La boîte de Pandore"
    players: 2-10
    duration: 10-50
    needs: [troublemaker]
  solo:
    description: Solo
    players: 1
    excludes: [pandora]
variants:
  points: Points
---
# Setup

Deal 7.

{9-10p} NINE-TEN.

{+troublemaker} TROUBLE.

{+pandora} PANDORA.
"""


def vault(tmp_path, game=GAME, extra=None):
    (tmp_path / "f").mkdir(exist_ok=True)
    (tmp_path / "f" / "f.game").write_text(game, encoding="utf-8")
    for name, text in (extra or {}).items():
        (tmp_path / name).write_text(text, encoding="utf-8")
    return tmp_path


def run(capsys, v, *args):
    code = tabula.main(["--vault", str(v), *args])
    out = capsys.readouterr()
    return code, out.out, out.err


def test_player_counts_from_extensions(tmp_path, capsys):
    v = vault(tmp_path)
    code, _, err = run(capsys, v, "show", "f", "-p", "10")
    assert code == 2 and "not 10 (with extensions: 2-10 +pandora, 1 +solo)" in err
    code, out, err = run(capsys, v, "show", "f", "-p", "10", "-e", "pandora", "--no-color")
    assert code == 0 and "NINE-TEN" in out and "PANDORA" in out
    assert "+pandora needs +troublemaker: turned it on" in err and "TROUBLE" in out
    assert run(capsys, v, "show", "f", "-p", "1", "-e", "solo")[0] == 0
    assert run(capsys, v, "show", "f", "-p", "9", "--all")[0] == 0              # --all: every option's counts


def test_excludes(tmp_path, capsys):
    code, _, err = run(capsys, vault(tmp_path), "show", "f", "-e", "solo", "-e", "pandora")
    assert code == 2 and "+solo and +pandora can't be used together" in err


def test_descriptions_and_terminal(tmp_path, capsys):
    v = vault(tmp_path)
    _, out, _ = run(capsys, v, "show", "f", "--no-color")
    assert "extensions: troublemaker, pandora (2-10p, needs troublemaker), solo (1p, not with pandora)" in out
    _, out, _ = run(capsys, v, "export", "f", "--interactive", "-o", "-")
    assert 'title="La boîte de Pandore · 2–10 players · 10–50 min · needs troublemaker"' in out    # the description, not the dict
    assert '<option value="10">10</option>' in out and '<option value="1">1</option>' in out
    assert "2–10 +pandora" in out                                            # the facts


def test_list_and_site(tmp_path, capsys):
    v = vault(tmp_path)
    _, out, _ = run(capsys, v, "list", "-p", "10")
    assert "2-8 (+pandora)" in out
    _, out, _ = run(capsys, v, "list", "-p", "11")
    assert "no games found" in out
    run(capsys, v, "site", "-o", str(tmp_path / "site"))
    index = (tmp_path / "site" / "index.html").read_text(encoding="utf-8")
    assert "1 2 3 4 5 6 7 8 9 10" in index


def test_translation_keeps_details(tmp_path, capsys):
    v = vault(tmp_path, extra={"f/f.fr.game": "---\ntitle: F\nextensions:\n  pandora: \"Pandore (fr)\"\n---\n# Mise en place\n\n{+pandora} PANDORE.\n"})
    code, out, err = run(capsys, v, "show", "f", "-l", "fr", "-p", "10", "-e", "pandora", "--no-color")
    assert code == 0 and "PANDORE" in out
    _, out, _ = run(capsys, v, "show", "f", "-l", "fr", "--json")
    assert json.loads(out)["meta"]["extensions"]["pandora"]["description"] == "Pandore (fr)"


def test_check(tmp_path, capsys):
    bad = GAME.replace("    needs: [troublemaker]", "    needs: [troublemaker, troublemakr]\n    playres: 3\n    duration: soon") \
              .replace("    excludes: [pandora]", "    excludes: [solo, ghost]")
    code, out, _ = run(capsys, vault(tmp_path, bad), "check", "--no-color")
    assert code == 1
    for msg in ("warning  f/f.game:1  'pandora': 'playres' looks like a typo of 'players'",
                "'pandora': invalid duration 'soon'",
                "'pandora' needs 'troublemakr', which is not declared under variants or extensions: did you mean "
                "'troublemaker'?", "'solo' excludes 'ghost', which is not declared", "'solo' excludes itself"):
        assert msg in out, msg
    code, out, _ = run(capsys, vault(tmp_path), "check", "--no-color")
    assert code == 0 and "never applies" not in out                           # {9-10p}: possible with pandora


BANDIDA = """---
title: Bandida
players: 1-4
language: fr
variants:
  amoureux:
    description: Les amoureux en cavale
    players: 2-8
    needs: [Bandido]
  troc:
    description: Troc
    needs: [amoureux, Un jeu absent]
---
# Règles

Texte.

{+amoureux} AMOUREUX.
"""


def bandida(tmp_path, with_bandido=True, title="Bandido"):
    (tmp_path / "bandida").mkdir(exist_ok=True)
    (tmp_path / "bandida" / "bandida.game").write_text(BANDIDA, encoding="utf-8")
    if with_bandido:
        (tmp_path / "le-bandido").mkdir(exist_ok=True)
        (tmp_path / "le-bandido" / "le-bandido.game").write_text(
            f"---\ntitle: {title}\nplayers: 1-4\n---\n# Règles\n\nTexte.\n", encoding="utf-8")
    return tmp_path


def test_needs_another_game(tmp_path, capsys):
    v = bandida(tmp_path)
    code, out, _ = run(capsys, v, "check", "--no-color")
    assert code == 0, out                                    # another game: not an undeclared variant
    code, out, err = run(capsys, v, "show", "bandida", "-v", "amoureux", "--no-color")
    assert code == 0 and "AMOUREUX" in out and "+amoureux needs the game Bandido" in err
    assert "amoureux (2-8p, needs Bandido)" in out
    code, out, err = run(capsys, v, "show", "bandida", "-v", "troc", "--no-color")
    assert "+troc needs +amoureux: turned it on" in err and "AMOUREUX" in out    # variants are still turned on
    assert "needs the game Un jeu absent" in err


def test_export_links_a_game_of_the_vault(tmp_path, capsys):
    v = bandida(tmp_path)                                    # found by its title: its file is le-bandido
    _, html, _ = run(capsys, v, "export", "bandida", "-o", "-")
    assert 'nécessite <a class="game" href="le-bandido.html">Bandido</a>' in html
    assert "nécessite amoureux, Un jeu absent<" in html      # not in the vault: plain text
    run(capsys, v, "site", "-o", str(tmp_path / "site"))
    page = (tmp_path / "site" / "bandida" / "index.html").read_text(encoding="utf-8")
    assert '<a class="game" href="../le-bandido/index.html">Bandido</a>' in page


def test_needed_game_found_by_file_name_or_translated_title(tmp_path, capsys):
    v = bandida(tmp_path, title="Le Bandit")
    _, html, _ = run(capsys, v, "export", "bandida", "-o", "-")
    assert '<a class="game"' not in html                     # 'Bandido' is neither its title nor its file name
    (tmp_path / "le-bandido" / "le-bandido.game").write_text(
        "---\ntitle: Bandido\nplayers: 1-4\nlanguage: es\n---\n# Reglas\n\nTexto.\n", encoding="utf-8")
    (tmp_path / "le-bandido" / "le-bandido.fr.game").write_text("---\ntitle: Le Bandit\n---\n# Règles\n", encoding="utf-8")
    (tmp_path / "bandida" / "bandida.game").write_text(BANDIDA.replace("[Bandido]", "[le bandit]"), encoding="utf-8")
    _, html, _ = run(capsys, v, "export", "bandida", "-o", "-")
    assert '<a class="game" href="le-bandido.html">le bandit</a>' in html
