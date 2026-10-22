"""Callouts: > [!exemple] Title, drawn as boxes by type."""
import json
import re

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


QUOTES = """# Tips

> [!remarque] Trois astuces
> - FIRST tip.
>
> - SECOND tip with a [[Card]].
>
> - THIRD tip,
>   CONTINUED on the next line.

> Plain note
> on TWO lines.

> PARA-ONE.
>
> {2p} PARA-TWO only for two.

# Glossary

Card
: A card.
"""


def test_paragraphs_and_lists_inside_quotes(tmp_path, capsys):
    v = game(tmp_path, QUOTES)
    tabula.main(["--vault", str(v), "show", "g", "--no-color", "-p", "3"])
    out = capsys.readouterr().out
    assert "┃ • FIRST tip.\n┃ • SECOND tip with a Card.\n┃ • THIRD tip, CONTINUED on the next line." in out
    assert "│ Plain note on TWO lines." in out
    assert "│ PARA-ONE." in out and "PARA-TWO" not in out                 # filtered inside the quote
    tabula.main(["--vault", str(v), "export", "g", "-o", "-"])
    html = capsys.readouterr().out
    assert re.search(r'<aside class="callout callout-info"><p class="callout-title">.*?</p>\s*<ul>\s*<li>FIRST tip\.', html, re.S)
    assert re.search(r"THIRD tip, CONTINUED on the next line\.\s*</li></ul></aside>", html)
    assert re.search(r'<aside class="note"><p>PARA-ONE\.</p>\s*<p>.*PARA-TWO', html, re.S)
    tabula.main(["--vault", str(v), "show", "g", "--json"])
    notes = [b for b in json.loads(capsys.readouterr().out)["blocks"] if b["kind"] == "note"]
    assert notes[0]["title"] == "Trois astuces" and [k["kind"] for k in notes[0]["body"]] == ["item", "item", "item"]
    code = tabula.main(["--vault", str(v), "check", "--no-color"])
    assert code == 0 and "never" not in capsys.readouterr().out          # [[Card]] in the list counts as used
