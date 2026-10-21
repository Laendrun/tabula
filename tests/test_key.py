"""`tabula show --key` / `tabula export --key`: a cheat sheet of the key rules and key sections."""
import json

import tabula

BODY = """# Play {#play}

NORMAL-TEXT.

- NORMAL-STEP
- ! KEY-STEP
  - KEY-STEP-DETAIL
- OTHER-STEP

! KEY-PARAGRAPH {3+p}

## ! When the tower falls

1. FALL-STOP.

### Exception {3+p}

FALL-EXCEPTION.

---

FALL-STILL.

## Ending

ENDING-TEXT.

# Setup {#setup}

SETUP-TEXT.

# Glossary {#glossary}

## Pieces {#cards}

Block
: BLOCK-TEXT.

---

Tower
: ! TOWER-KEY.
"""


def game(tmp_path, body=BODY):
    (tmp_path / "g").mkdir(exist_ok=True)
    (tmp_path / "g" / "g.game").write_text(f"---\ntitle: G\nplayers: 2-4\n---\n{body}", encoding="utf-8")
    return tmp_path


def run(capsys, vault, cmd, *args):
    extra = ["--no-color"] if cmd == "show" else ["-o", "-"]
    code = tabula.main(["--vault", str(vault), cmd, "g", *extra, *args])
    out = capsys.readouterr()
    return code, out.out, out.err


def test_only_key_rules_and_key_sections(tmp_path, capsys):
    code, out, _ = run(capsys, game(tmp_path), "show", "--key")
    assert code == 0 and "Showing: key rules" in out
    for word in ("KEY-STEP", "KEY-STEP-DETAIL", "KEY-PARAGRAPH", "FALL-STOP", "FALL-EXCEPTION", "FALL-STILL",
                 "TOWER-KEY"):
        assert word in out, word
    for word in ("NORMAL-TEXT", "NORMAL-STEP", "OTHER-STEP", "ENDING-TEXT", "SETUP-TEXT", "BLOCK-TEXT"):
        assert word not in out, word


def test_headings_give_context(tmp_path, capsys):
    _, out, _ = run(capsys, game(tmp_path), "show", "-k")
    assert "PLAY" in out and "GLOSSARY" in out          # the sections the key rules are in
    assert "SETUP" not in out and "Ending" not in out   # sections without key rules
    assert "Pieces" not in out                          # "Tower" comes after the "---" that closes it


def test_filters_still_apply(tmp_path, capsys):
    _, out, _ = run(capsys, game(tmp_path), "show", "-k", "-p", "2")
    assert "KEY-PARAGRAPH" not in out and "FALL-EXCEPTION" not in out and "FALL-STOP" in out


def test_json(tmp_path, capsys):
    _, out, _ = run(capsys, game(tmp_path), "show", "-k", "--json")
    data = json.loads(out)
    assert data["key_sections"] == ["When the tower falls"]
    assert "KEY-STEP" in data["key_rules"]


def test_no_key_rules(tmp_path, capsys):
    code, _, err = run(capsys, game(tmp_path, "# Play\n\nNothing key here.\n"), "show", "-k")
    assert code == 1 and "no key rules in G" in err


def test_export_key(tmp_path, capsys):
    vault = game(tmp_path)
    code, html, _ = run(capsys, vault, "export", "-k")
    assert code == 0 and "<title>G — key rules</title>" in html
    assert "FALL-STOP" in html and "NORMAL-TEXT" not in html
    assert tabula.main(["--vault", str(vault), "export", "g", "-k", "-p", "3", "-o", str(tmp_path)]) == 0
    assert (tmp_path / "g-3p-key.html").exists()


def test_consecutive_key_lines_are_one_rule(tmp_path, capsys):
    body = ("# Setup\n\n"
            "! FIRST-LINE of the rule.\n! SECOND-LINE of the same rule, with a [[Queen]].\n\n"
            "! SEPARATE-RULE after a blank line.\nCONTINUED without an exclamation mark.\n\n"
            "! BROKEN-REF line.\n! Here [[nowhere]] is.\n\n"
            "# Glossary\n\nQueen\n: A card.\n")
    vault = game(tmp_path, body)
    code, out, _ = run(capsys, vault, "show", "--json")
    rules = json.loads(out)["key_rules"]
    assert rules == ["FIRST-LINE of the rule. SECOND-LINE of the same rule, with a Queen.",
                     "SEPARATE-RULE after a blank line. CONTINUED without an exclamation mark.",
                     "BROKEN-REF line. Here nowhere is."]
    _, out, _ = run(capsys, vault, "show")
    assert out.count("★") == 3
    tabula.main(["--vault", str(vault), "check", "--no-color"])
    out = capsys.readouterr().out
    assert "g.game:14  [[nowhere]] matches no component" in out        # the line it's written on
    assert "Queen" not in out                                          # [[Queen]] on the 2nd line counts
