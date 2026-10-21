"""Score sheets (.sheet): player columns, rounds, merged and shaded cells, paper size; check, fmt, site."""
import io
import json
import re
import sys

import pytest

import tabula
from tabula.sheet import expand_grid

GAME = "---\ntitle: G\nplayers: 2-4\nsymbols:\n  or: 🪙\n---\n# Rules\n\nPlay.\n"
SHEET = """---
title: Scores
size: a5
orientation: landscape
rounds: 3
---

# Partie :or:

| Manche | Joueur {n} | <  |
|--------|------------|----|
|        | pts        | Σ  |
| {r}    |            |    |
| Bonus  | //         |    |

---

| Total | {player} |
|-------|----------|
| :or:  |          |
"""


def vault(tmp_path, sheet=SHEET, name="g", game=GAME):
    root = tmp_path / "v"
    (root / "g").mkdir(parents=True, exist_ok=True)
    (root / "g" / "g.game").write_text(game, encoding="utf-8")
    (root / "g" / f"{name}.sheet").write_text(sheet, encoding="utf-8")
    return root


def render(capsys, root, *args):
    code = tabula.main(["--vault", str(root), "sheet", "g", *args, "-o", "-"])
    return code, capsys.readouterr().out


def test_expand_grid():
    rows = [["Manche", "Joueur {n}", "<", "Note"], ["", "pts", "Σ", ""], ["{r}", "", "", "x"], ["Bonus", "//", "", ""]]
    out = expand_grid(rows, players=2, rounds=2)
    assert out[0] == ["Manche", "Joueur 1", "<", "Joueur 2", "<", "Note"]
    assert out[1] == ["", "pts", "Σ", "pts", "Σ", ""]
    assert [r[0] for r in out[2:]] == ["1", "2", "Bonus"]
    assert out[4] == ["Bonus", "//", "", "//", "", ""]
    assert expand_grid([["Nom", "{player}"]], 3, 1)[0] == ["Nom", "", "", ""]
    assert expand_grid([["a", "b"], ["c", "d"]], 5, 5) == [["a", "b"], ["c", "d"]]     # a plain grid stays


def test_player_columns_follow_p(tmp_path, capsys):
    root = vault(tmp_path)
    _, html = render(capsys, root)
    assert html.count("Joueur ") == 4 and "Joueur 4" in html                 # the game's most: 4
    _, html = render(capsys, root, "-p", "2")
    assert "Joueur 2" in html and "Joueur 3" not in html
    assert html.count('<th colspan="2">') == 2                              # Joueur {n} with its < column
    with pytest.raises(SystemExit, match="for 2-4 players, not 6"):
        render(capsys, root, "-p", "6")


def test_page_rounds_cells(tmp_path, capsys):
    _, html = render(capsys, vault(tmp_path), "-p", "3")
    assert "@page { size: 210mm 148mm" in html                               # A5 landscape
    assert html.count('<section class="page">') == 2                         # --- starts a new page
    assert re.findall(r"<th>(\d)</th>", html) == ["1", "2", "3"]             # rounds: 3
    assert html.count('<td class="x"></td>') == 3                            # one // per player
    assert '<img' not in html and "🪙" in html                               # the game's symbols
    assert "<thead><tr><th>Total</th><th></th><th></th><th></th></tr></thead>" in html     # names to write


def test_merges_and_free_grid(tmp_path, capsys):
    sheet = "---\nsize: a4\n---\n| A | B | < |\n|---|---|---|\n| x |   |   |\n| y | ^ | z |\n\n| | |\n|-|-|\n| | |\n"
    _, html = render(capsys, vault(tmp_path, sheet))
    assert '<th colspan="2">B</th>' in html and '<td rowspan="2"></td>' in html
    assert "@page { size: 210mm 297mm" in html
    assert html.count("<thead>") == 1                                        # an empty heading row is left out


def test_files_and_names(tmp_path, capsys, monkeypatch):
    root = vault(tmp_path, name="manches")
    (root / "g" / "points.sheet").write_text("---\ntitle: Points\n---\n| a | {player} |\n|---|---|\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    assert tabula.main(["--vault", str(root), "sheet", "g", "--list"]) == 0
    out = capsys.readouterr().out
    assert "manches" in out and "Scores  (A5, landscape)" in out and "Points  (A4, portrait)" in out
    assert tabula.main(["--vault", str(root), "sheet", "g"]) == 0
    assert (tmp_path / "g-manches.html").exists() and (tmp_path / "g-points.html").exists()
    assert tabula.main(["--vault", str(root), "sheet", "g", "points", "3"]) == 0          # name, then players
    assert (tmp_path / "g-points-3p.html").exists()
    assert tabula.main(["--vault", str(root), "sheet", str(root / "g" / "points.sheet"), "-o", "-"]) == 0


def test_stdin(tmp_path, capsys, monkeypatch):
    root = vault(tmp_path)
    f = root / "g" / "g.sheet"
    monkeypatch.setattr(sys, "stdin", io.TextIOWrapper(io.BytesIO("| Unsaved | {player} |\n|---|---|\n".encode())))
    assert tabula.main(["--vault", str(root), "sheet", str(f), "--stdin", "-o", "-"]) == 0
    assert "Unsaved" in capsys.readouterr().out


def test_check(tmp_path, capsys):
    bad = ("---\nsize: a9\norientation: sideways\nmargn: 5\n---\n| A | B |\n|---|---|\n| < | x |\n| ^ | y | z |\n"
           "\nPay :orr:.\n")
    root = vault(tmp_path, bad)
    code = tabula.main(["--vault", str(root), "check", "--no-color"])
    out = capsys.readouterr().out
    assert code == 1
    for msg in ("g.sheet:1  unknown size 'a9'", "orientation must be portrait or landscape",
                "'margn:' in frontmatter: did you mean 'margin'?", "g.sheet:8  '<' in the first column",
                "g.sheet:9  this row has 3 cells", "':orr:' is not a symbol: did you mean ':or:'?"):
        assert msg in out, msg
    code = tabula.main(["--vault", str(root), "check", str(root / "g" / "g.sheet"), "--json"])
    data = json.loads(capsys.readouterr().out)
    assert code == 1 and data["files"] == [str((root / "g" / "g.sheet").resolve())]
    assert {i["level"] for i in data["issues"]} == {"error", "warning"}
    tabula.main(["--vault", str(root), "check", "g", "--json"])
    assert str(root / "g" / "g.sheet") in json.loads(capsys.readouterr().out)["files"]


def test_fmt_and_site(tmp_path, capsys):
    root = vault(tmp_path, "---\ntitle: S\n---\n| Joueur | {player} |\n|---|---|\n| Points | |\n")
    assert tabula.main(["--vault", str(root), "fmt"]) == 0
    assert "| Joueur | {player} |\n|--------|----------|\n| Points |          |" in (root / "g" / "g.sheet").read_text()
    capsys.readouterr()
    tabula.main(["--vault", str(root), "site", "-o", str(tmp_path / "site")])
    page = (tmp_path / "site" / "g" / "index.html").read_text(encoding="utf-8")
    assert '<a href="sheet-g.html" title="S">Score sheet ⎙</a>' in page
    assert "<table>" in (tmp_path / "site" / "g" / "sheet-g.html").read_text(encoding="utf-8")


def test_standalone_game_sheet(tmp_path, capsys):
    (tmp_path / "solo.game").write_text("---\ntitle: Solo\nplayers: 1-2\n---\n# R\n\nX.\n", encoding="utf-8")
    (tmp_path / "solo.sheet").write_text("| Score | {player} |\n|---|---|\n", encoding="utf-8")
    assert tabula.main(["--vault", str(tmp_path), "sheet", "solo", "-o", "-"]) == 0
    assert capsys.readouterr().out.count("<th></th>") == 2
