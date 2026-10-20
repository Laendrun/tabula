"""Shared fragments: `![[name]]` / `![[name#Section]]` include vault/_shared/name.game."""
import io
import json
import sys

import pytest

import tabula

DECK = """---
title: Standard deck
---
<!-- TODO: add a picture -->

# Components {#components}

- 52x [[playing card]]
  - 13x [[spade|spades]]
- {+jokers} 2x [[joker]]

# Glossary {#glossary}

Playing card
: DECK-CARD one of 52.

Spade
: DECK-SPADE black suit.

## Optional {+jokers}

Joker
: DECK-JOKER wild.

### Joker details

DETAILS-TEXT.

---

AFTER-OPTIONAL in the glossary.

# Notes

NOTES-TEXT.
"""

DECK_FR = """# Matériel {#components}

- 52x [[carte]]

# Glossaire {#glossary}

Carte
: DECK-CARTE une des 52.
"""

GAME = """---
title: President
players: 3-7
variants:
  jokers: "With jokers"
---
# Components {#components}

![[deck-52#components]]
- 1x [[score pad]]

# Play

Deal the [[playing cards]].

# Glossary {#glossary}

![[deck-52#Glossary]]

Score pad
: PAD-TEXT.
"""


@pytest.fixture
def vault(tmp_path):
    (tmp_path / "_shared").mkdir()
    (tmp_path / "_shared" / "deck-52.game").write_text(DECK, encoding="utf-8")
    (tmp_path / "_shared" / "deck-52.fr.game").write_text(DECK_FR, encoding="utf-8")
    (tmp_path / "president").mkdir()
    (tmp_path / "president" / "president.game").write_text(GAME, encoding="utf-8")
    return tmp_path


def add(vault, slug, body, meta="players: 2"):
    (vault / slug).mkdir(exist_ok=True)
    (vault / slug / f"{slug}.game").write_text(f"---\ntitle: {slug}\n{meta}\n---\n{body}", encoding="utf-8")


def run(capsys, vault, *args):
    code = tabula.main(["--vault", str(vault), *args])
    out = capsys.readouterr()
    return code, out.out, out.err


def test_sections_are_included_where_they_are_written(vault, capsys):
    code, out, _ = run(capsys, vault, "show", "president", "--no-color")
    assert code == 0
    components = out[out.index("COMPONENTS"):out.index("PLAY")]
    assert "52x playing card" in components and "13x spades" in components and "1x score pad" in components
    glossary = out[out.index("GLOSSARY"):]
    assert "DECK-CARD" in glossary and "DECK-SPADE" in glossary and "PAD-TEXT" in glossary
    assert "NOTES-TEXT" not in out                     # only the sections asked for
    assert "DECK-JOKER" not in out                     # the fragment's {+jokers} part follows the game's variant


def test_fragment_conditions_follow_the_game(vault, capsys):
    _, out, _ = run(capsys, vault, "show", "president", "-v", "jokers", "--no-color")
    assert "2x joker" in out and "DECK-JOKER" in out and "DETAILS-TEXT" in out
    # the game's own term after the include is back in the game's glossary, not in the fragment's
    # "{+jokers}" sub-section, and closing that sub-section shows no separator
    assert "PAD-TEXT" in out and out.count("· · ·") == 1       # only the fragment's own "---"
    g = tabula.Vault(vault).load(vault / "president" / "president.game")
    from tabula.filtering import select_sections
    assert any(b.kind == "def" and b.term == "Score pad" for b in select_sections(
        tabula.filter_blocks(g.blocks, tabula.Ctx(None, set(), False)), ["glossary"]))


def test_included_headings_nest_under_the_section(vault, capsys):
    g = tabula.Vault(vault).load(vault / "president" / "president.game")
    heads = [(b.level, b.text) for b in g.blocks if b.kind == "heading" and not b.reopens]
    # "## Optional" (level 2 under "# Glossary" in the fragment) lands one level below "# Glossary" in the game
    assert (2, "Optional") in heads and (3, "Joker details") in heads
    assert [t for _, t in heads].count("Glossary") == 1      # the selected heading itself isn't repeated


def test_whole_fragment_and_indentation(vault, capsys):
    add(vault, "solo", "# Rules\n\n![[deck-52]]\n\n# Kit\n\n- 1x [[box]]\n  ![[deck-52#components]]\n")
    g = tabula.Vault(vault).load(vault / "solo" / "solo.game")
    heads = [(b.level, b.text) for b in g.blocks if b.kind == "heading" and not b.reopens]
    assert (2, "Components") in heads and (2, "Notes") in heads and (3, "Optional") in heads
    parts = {c["name"]: c.get("part_of") for c in tabula.components_of(g.blocks)}
    assert parts["playing card"] == "box" and parts["spade"] == "playing card"   # indented include = nested parts


def test_translations_use_the_translated_fragment(vault, capsys):
    (vault / "president" / "president.fr.game").write_text(
        "---\ntitle: Président\n---\n# Matériel\n\n![[deck-52#components]]\n\n# Lexique\n\n![[deck-52#glossary]]\n",
        encoding="utf-8")
    _, out, _ = run(capsys, vault, "show", "president", "-l", "fr", "--no-color")
    assert "52x carte" in out and "DECK-CARTE" in out and "DECK-CARD" not in out


def test_fragment_folder_is_not_a_game(vault, capsys):
    _, out, _ = run(capsys, vault, "list")
    assert "president" in out and "deck-52" not in out and "_shared" not in out


def test_check_reports_problems_at_the_include_line(vault, capsys):
    add(vault, "broken", "# Rules\n\n![[nowhere]]\n\n![[deck-52#Missing]]\n\n![[deck-52]]\n\nSee ![[deck-52]] here.\n")
    code, out, _ = run(capsys, vault, "check", "broken", "--no-color")
    assert code == 1
    assert "broken.game:7  no shared fragment 'nowhere': looked for _shared/nowhere.game" in out
    assert "broken.game:9  no section 'Missing' in _shared/deck-52.game; sections: Components #components" in out
    assert out.count("broken.game:11  '+jokers' is not declared") == 1       # reported once, at the include line
    assert "broken.game:13  '![[deck-52]]' includes a shared fragment only when it is alone on its line" in out


def test_check_covers_fragments_on_their_own(vault, capsys):
    code, out, _ = run(capsys, vault, "check", "--no-color")
    assert code == 0
    assert "_shared/deck-52" in out and "ok  (1 TODO)" in out
    assert "1 game(s), 1 fragment(s)" in out
    (vault / "_shared" / "deck-52.game").write_text(DECK + "\nSee [[open\n", encoding="utf-8")
    code, out, _ = run(capsys, vault, "check", "--no-color")
    assert code == 1 and "_shared/deck-52.game:" in out and "unclosed '[['" in out


def test_check_an_unsaved_fragment(vault, capsys, monkeypatch):
    frag = vault / "_shared" / "deck-52.game"
    monkeypatch.setattr(sys, "stdin", io.TextIOWrapper(io.BytesIO(b"# A\n\nSee [[open\n"), encoding="utf-8"))
    code, out, _ = run(capsys, vault, "check", str(frag), "--json", "--stdin")
    issues = json.loads(out)["issues"]
    assert code == 1 and [(i["line"], i["level"]) for i in issues] == [(3, "error")]
    assert "missing required" not in out                   # a fragment needs no title or players


def test_nested_fragments_and_cycles(vault, capsys):
    (vault / "_shared" / "outer.game").write_text("# Outer\n\n![[deck-52#glossary]]\n", encoding="utf-8")
    (vault / "_shared" / "loop.game").write_text("# Loop\n\n![[loop]]\n", encoding="utf-8")
    add(vault, "nest", "# Glossary\n\n![[outer]]\n\nUse [[spades]].\n\n# Again\n\n![[loop]]\n")
    code, out, _ = run(capsys, vault, "check", "nest", "--no-color")
    assert "nest.game:13  'loop' includes itself (through loop)" in out
    _, out, _ = run(capsys, vault, "show", "nest", "--no-color")
    assert "DECK-SPADE" in out


def test_todo_lists_fragment_reminders(vault, capsys):
    _, out, _ = run(capsys, vault, "todo", "--no-color")
    assert "(_shared/deck-52)" in out and "deck-52.game:4  add a picture" in out


def test_site_and_export_use_fragments(vault, capsys, tmp_path):
    assert run(capsys, vault, "site", "-o", str(tmp_path / "site"))[0] == 0
    assert not (tmp_path / "site" / "_shared").exists() and not (tmp_path / "site" / "deck-52").exists()
    page = (tmp_path / "site" / "president" / "index.html").read_text(encoding="utf-8")
    assert "DECK-CARD" in page and 'href="#t-playing-card"' in page
