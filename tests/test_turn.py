"""The turn summary: #turn sections, then the key rules found elsewhere."""
import json

import tabula

BODY = """# Setup {#setup}

SETUP-TEXT.

! SETUP-KEY.

# Play {#play}

INTRO-TEXT.

## Your turn {#turn}

1. TURN-ONE.
2. TURN-TWO.

! TURN-KEY.

### Detail

TURN-DETAIL.

## Special cases

CASE-TEXT.

## ! When the deck runs out

DECK-RULE.

# Glossary {#glossary}

Card
: CARD-TEXT.
"""


def vault(tmp_path, body=BODY):
    (tmp_path / "g").mkdir(parents=True, exist_ok=True)
    (tmp_path / "g" / "g.game").write_text(f"---\ntitle: G\nplayers: 2-4\n---\n{body}", encoding="utf-8")
    return tmp_path


def test_show(tmp_path, capsys):
    tabula.main(["--vault", str(vault(tmp_path)), "show", "g", "--turn", "--no-color"])
    out = capsys.readouterr().out
    assert "Showing: turn summary" in out
    for w in ("TURN-ONE", "TURN-TWO", "TURN-KEY", "TURN-DETAIL", "SETUP-KEY", "DECK-RULE"):
        assert w in out, w
    for w in ("SETUP-TEXT", "INTRO-TEXT", "CASE-TEXT", "CARD-TEXT"):
        assert w not in out, w
    assert out.index("TURN-ONE") < out.index("SETUP-KEY")            # the turn first, then the key rules
    assert out.count("TURN-KEY") == 1


def test_json_levels(tmp_path, capsys):
    tabula.main(["--vault", str(vault(tmp_path)), "show", "g", "-t", "--json"])
    heads = [(b["text"], b["level"]) for b in json.loads(capsys.readouterr().out)["blocks"] if b["kind"] == "heading"]
    assert heads[:2] == [("Your turn", 1), ("Detail", 2)]                # promoted: the summary starts with it


def test_no_turn_section(tmp_path, capsys):
    code = tabula.main(["--vault", str(vault(tmp_path, "# Play\n\nX.\n")), "show", "g", "--turn"])
    assert code == 1 and "#turn" in capsys.readouterr().err


def test_export_and_paper(tmp_path, capsys):
    v = vault(tmp_path)
    tabula.main(["--vault", str(v), "export", "g", "--turn", "--paper", "a5", "-o", "-"])
    html = capsys.readouterr().out
    assert "<title>G — turn summary</title>" in html and "@page{size:148mm 210mm" in html
    assert "SETUP-TEXT" not in html and "TURN-ONE" in html
    assert tabula.main(["--vault", str(v), "export", "g", "-t", "-o", str(tmp_path)]) == 0
    assert (tmp_path / "g-turn.html").exists()


def test_site(tmp_path, capsys):
    v = vault(tmp_path)
    tabula.main(["--vault", str(v), "site", "-o", str(tmp_path / "site")])
    page = (tmp_path / "site" / "g" / "turn.html").read_text(encoding="utf-8")
    assert '<span class="here">Turn summary</span>' in page and "TURN-ONE" in page
    assert '<a href="turn.html">Turn summary</a>' in (tmp_path / "site" / "g" / "index.html").read_text(encoding="utf-8")
    tabula.main(["--vault", str(vault(tmp_path / "x", "# Play\n\nX.\n")), "site", "-o", str(tmp_path / "s2")])
    assert not (tmp_path / "s2" / "g" / "turn.html").exists()
