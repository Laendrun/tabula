"""Callouts: > [!exemple] Title, drawn as boxes by type."""
import json

import tabula
from tabula.blocks import callout_family

BODY = ("# Rules\n\n> [!exemple] Un tour à 3\n> Alice joue un 7.\n> Bob passe.\n\n> [!Attention]\n> Ne **jamais** mélanger.\n\n"
        "> [!précision]\n> {2p} À deux : rien.\n\n> [!lore]\n> Il était une fois.\n\n> Une note.\n\n- Étape\n  > [!tip]\n  > Dans une liste.\n")


def game(tmp_path, body=BODY):
    (tmp_path / "g").mkdir(exist_ok=True)
    (tmp_path / "g" / "g.game").write_text(f"---\ntitle: G\nplayers: 2-4\n---\n{body}", encoding="utf-8")
    return tmp_path


def test_families():
    assert [callout_family(k) for k in ("Exemple", "ATTENTION", "astuce", "Précision", "faq", "lore", "Beispiel")] == \
        ["example", "warning", "tip", "info", "question", "note", "example"]


def test_terminal_and_json(tmp_path, capsys):
    v = game(tmp_path)
    tabula.main(["--vault", str(v), "show", "g", "--no-color", "-p", "3"])
    out = capsys.readouterr().out
    assert "┃ ◆ Un tour à 3\n┃ Alice joue un 7. Bob passe." in out
    assert "┃ ⚠ Attention\n┃ Ne jamais mélanger." in out
    assert "ℹ Précision" not in out                      # its only line is for 2 players: the whole box goes
    assert "┃ ▪ Lore" in out and "│ Une note." in out
    assert "    ┃ ✦ Tip\n    ┃ Dans une liste." in out
    tabula.main(["--vault", str(v), "show", "g", "--json"])
    blocks = json.loads(capsys.readouterr().out)["blocks"]
    notes = [b for b in blocks if b["kind"] == "note"]
    assert notes[0] == {"kind": "note", "line": 7, "text": "Alice joue un 7. Bob passe.", "callout": "exemple",
                        "title": "Un tour à 3"}
    assert notes[1]["title"] == "Attention" and "callout" not in notes[4]


def test_html(tmp_path, capsys):
    tabula.main(["--vault", str(game(tmp_path)), "export", "g", "-o", "-"])
    html = capsys.readouterr().out
    assert ('<aside class="callout callout-example"><p class="callout-title"><span class="icon" aria-hidden="true">◆'
            '</span> Un tour à 3</p><p>Alice joue un 7. Bob passe.</p></aside>') in html
    assert 'class="callout callout-warning"' in html and 'class="callout callout-note"' in html
    assert '<aside class="note"><p>Une note.</p></aside>' in html
