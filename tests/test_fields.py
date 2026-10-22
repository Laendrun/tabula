"""Your own frontmatter keys and extension details (shown as they are), and `year`."""
import json

import tabula
from tabula.fields import extra_fields, label, text

GAME = """---
title: F
players: 2-4
year: 2018
series: Rulefactory
bought_at: Spiel 2019
sleeved: true
BGG rank: 1234
empty:
extensions:
  pandora:
    description: Pandora's Box
    year: 2020
    players: 2-6
    box: blue
    cards: [Pandora, Hope]
  bare:
variants:
  points: Points
---
# Setup

Deal 7.
"""


def vault(tmp_path, game=GAME):
    (tmp_path / "f").mkdir(exist_ok=True)
    (tmp_path / "f" / "f.game").write_text(game, encoding="utf-8")
    return tmp_path


def run(capsys, v, *args):
    code = tabula.main(["--vault", str(v), *args])
    o = capsys.readouterr()
    return code, o.out, o.err


def test_labels_and_values():
    assert label("bought_at") == "Bought at" and label("BGG rank") == "BGG rank"
    assert text([1, "a", None]) == "1, a" and text(True, "fr") == "oui" and text({"a_b": 1}) == "A b: 1"
    assert extra_fields({"title": "x", "mine": "y", "none": None}) == [("Mine", "y")]


def test_check_allows_own_keys(tmp_path, capsys):
    code, out, _ = run(capsys, vault(tmp_path), "check", "--no-color")
    assert code == 0 and "warning" not in out.split("\n\n")[-1].replace("0 warning(s)", ""), out
    bad = GAME.replace("year: 2018", "year: soon").replace("    year: 2020", "    yearr: 2020\n    year: later")
    code, out, _ = run(capsys, vault(tmp_path, bad), "check", "--no-color")
    assert code == 0
    assert "year should be the year the game came out, e.g. 2019 (got 'soon')" in out
    assert "'pandora': 'yearr' looks like a typo of 'year'" in out
    assert "'pandora': year should be a year" in out


def test_export(tmp_path, capsys):
    _, out, _ = run(capsys, vault(tmp_path), "export", "f", "-o", "-")
    assert "<b>Year</b> 2018" in out
    assert '<p class="credits details"><b>Series</b> Rulefactory &nbsp; <b>Bought at</b> Spiel 2019 &nbsp; ' \
           '<b>Sleeved</b> yes &nbsp; <b>BGG rank</b> 1234</p>' in out
    assert "<b>Empty</b>" not in out
    assert ("<li><b>Pandora&#x27;s Box</b> <code>+pandora</code> <span class=\"more\">2020 · 2–6 players · "
            "Box: blue · Cards: Pandora, Hope</span></li>") in out
    assert "<b>Points</b> <code>+points</code></li>" in out and "<b>bare</b>" not in out
    _, out, _ = run(capsys, vault(tmp_path), "export", "f", "--interactive", "-o", "-")
    assert 'title="Pandora&#x27;s Box · 2020 · 2–6 players · Box: blue · Cards: Pandora, Hope"' in out


def test_show_list_site(tmp_path, capsys):
    v = vault(tmp_path)
    _, out, _ = run(capsys, v, "show", "f", "--no-color")
    assert "2-4 players · 2018" in out
    assert "Series: Rulefactory · Bought at: Spiel 2019 · Sleeved: yes · BGG rank: 1234" in out
    assert "pandora (2020, 2-6p, Box: blue, Cards: Pandora, Hope)" in out
    _, out, _ = run(capsys, v, "show", "f", "--json")
    assert json.loads(out)["meta"]["series"] == "Rulefactory"
    _, out, _ = run(capsys, v, "list", "--json")
    assert json.loads(out)["games"][0]["year"] == 2018
    run(capsys, v, "site", "-o", str(tmp_path / "site"))
    assert "2018" in (tmp_path / "site" / "index.html").read_text(encoding="utf-8")
