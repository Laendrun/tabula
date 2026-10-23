"""The rules summary: #summary sections, then the key rules found elsewhere (and #turn with --turn)."""
import json

import tabula

BODY = """# In short {#summary}

SUMMARY-TEXT.

## Winning

SUMMARY-DETAIL.

# Setup {#setup}

SETUP-TEXT.

! SETUP-KEY.

# Play {#play}

INTRO-TEXT.

## Your turn {#turn}

TURN-ONE.

! TURN-KEY.

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
    tabula.main(["--vault", str(vault(tmp_path)), "show", "g", "--summary", "--no-color"])
    out = capsys.readouterr().out
    assert "Showing: rules summary" in out
    for w in ("SUMMARY-TEXT", "SUMMARY-DETAIL", "SETUP-KEY", "TURN-KEY", "DECK-RULE"):
        assert w in out, w
    for w in ("SETUP-TEXT", "INTRO-TEXT", "TURN-ONE", "CARD-TEXT"):
        assert w not in out, w
    assert out.index("SUMMARY-TEXT") < out.index("SETUP-KEY")         # the summary first, then the key rules


def test_with_the_turn(tmp_path, capsys):
    tabula.main(["--vault", str(vault(tmp_path)), "show", "g", "--summary", "--turn", "--no-color"])
    out = capsys.readouterr().out
    assert out.index("SUMMARY-TEXT") < out.index("TURN-ONE") < out.index("SETUP-KEY")
    assert out.count("TURN-KEY") == 1 and "INTRO-TEXT" not in out


def test_the_summary_is_also_in_the_rules(tmp_path, capsys):
    tabula.main(["--vault", str(vault(tmp_path)), "show", "g", "--no-color"])
    out = capsys.readouterr().out
    assert "SUMMARY-TEXT" in out and "SETUP-TEXT" in out


def test_json_levels(tmp_path, capsys):
    body = BODY.replace("# In short {#summary}", "## In short {#summary}").replace("## Winning", "### Winning")
    tabula.main(["--vault", str(vault(tmp_path, body)), "show", "g", "--summary", "--json"])
    heads = [(b["text"], b["level"]) for b in json.loads(capsys.readouterr().out)["blocks"] if b["kind"] == "heading"]
    assert heads[:2] == [("In short", 1), ("Winning", 2)]


def test_no_summary_section(tmp_path, capsys):
    v = vault(tmp_path, "# Play {#turn}\n\nX.\n")
    assert tabula.main(["--vault", str(v), "show", "g", "--summary"]) == 1
    assert "#summary" in capsys.readouterr().err
    assert tabula.main(["--vault", str(v), "export", "g", "--summary", "--turn", "-o", "-"]) == 1   # not the turn alone


def test_export_and_paper(tmp_path, capsys):
    v = vault(tmp_path)
    tabula.main(["--vault", str(v), "export", "g", "--summary", "--paper", "a5", "-o", "-"])
    html = capsys.readouterr().out
    assert "<title>G — quick rules</title>" in html and "@page{size:148mm 210mm" in html
    assert "SETUP-TEXT" not in html and "SUMMARY-TEXT" in html and "DECK-RULE" in html
    assert tabula.main(["--vault", str(v), "export", "g", "--summary", "-o", str(tmp_path)]) == 0
    assert (tmp_path / "g-summary.html").exists()


def test_french_label(tmp_path, capsys):
    (tmp_path / "g").mkdir()
    (tmp_path / "g" / "g.game").write_text("---\ntitle: G\nplayers: 2-4\nlanguage: fr\n---\n"
                                           "# En bref {#summary}\n\nRÉSUMÉ.\n", encoding="utf-8")
    tabula.main(["--vault", str(tmp_path), "export", "g", "--summary", "-o", "-"])
    assert "<title>G — règles en bref</title>" in capsys.readouterr().out


def test_site(tmp_path, capsys):
    v = vault(tmp_path)
    tabula.main(["--vault", str(v), "site", "-o", str(tmp_path / "site")])
    page = (tmp_path / "site" / "g" / "summary.html").read_text(encoding="utf-8")
    assert '<span class="here">Quick rules</span>' in page and "SUMMARY-TEXT" in page and "TURN-ONE" not in page
    index = (tmp_path / "site" / "g" / "index.html").read_text(encoding="utf-8")
    assert '<a href="summary.html">Quick rules</a>' in index and '<a href="turn.html">Turn summary</a>' in index
    assert index.index("summary.html") < index.index("turn.html")
    tabula.main(["--vault", str(vault(tmp_path / "x", "# Play\n\nX.\n")), "site", "-o", str(tmp_path / "s2")])
    assert not (tmp_path / "s2" / "g" / "summary.html").exists()


def test_check_knows_the_role(tmp_path, capsys):
    v = vault(tmp_path, "# In short {#sumary}\n\nX.\n")
    tabula.main(["--vault", str(v), "check", "--no-color"])
    assert "#summary" in capsys.readouterr().out                    # "did you mean"
