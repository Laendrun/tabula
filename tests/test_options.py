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
    assert 'title="La boîte de Pandore"' in out                               # the description, not the dict
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
    bad = GAME.replace("    needs: [troublemaker]", "    needs: [troublemaker, ghost]\n    playres: 3\n    duration: soon") \
              .replace("    excludes: [pandora]", "    excludes: [solo]")
    code, out, _ = run(capsys, vault(tmp_path, bad), "check", "--no-color")
    assert code == 1
    for msg in ("'pandora': unknown detail 'playres' (did you mean 'players'?)", "'pandora': invalid duration 'soon'",
                "'pandora' needs 'ghost', which is not declared", "'solo' excludes itself"):
        assert msg in out, msg
    code, out, _ = run(capsys, vault(tmp_path), "check", "--no-color")
    assert code == 0 and "never applies" not in out                           # {9-10p}: possible with pandora
