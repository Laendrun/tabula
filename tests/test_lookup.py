"""`tabula lookup`: find one term at the table (exact, partial, accents, typos) with filters."""
import json

import pytest

import tabula
from conftest import FIXTURES


@pytest.fixture
def lookup(capsys):
    def run(*args):
        code = tabula.main(["--vault", str(FIXTURES), "lookup", "kitchen-sink", "--no-color", *args])
        out = capsys.readouterr()
        return code, out.out, out.err
    return run


def test_exact_match_wins_over_longer_names(lookup):
    code, out, _ = lookup("card")
    assert code == 0 and "VICTOR" in out
    assert "WHISKEY" not in out and "ACTION-TEXT" not in out      # "Number card", "Action card" not shown


def test_case_plural_and_partial(lookup):
    assert "WHISKEY" in lookup("NUMBER", "CARDS")[1]
    assert "ACTION-TEXT" in lookup("action")[1]


def test_accents_are_ignored(tmp_path, capsys):
    (tmp_path / "g").mkdir()
    (tmp_path / "g" / "g.game").write_text(
        "---\ntitle: G\nplayers: 2\n---\n# Lexique\n\nÉvénement\n: EVENT-TEXT\n", encoding="utf-8")
    assert tabula.main(["--vault", str(tmp_path), "lookup", "g", "evenements", "--no-color"]) == 0
    out = capsys.readouterr().out
    assert "EVENT-TEXT" in out and "closest" not in out          # a direct match, not a typo guess


def test_typo_shows_the_closest(lookup):
    code, out, _ = lookup("rokcet")
    assert code == 0 and "showing the closest" in out and "ZULU" in out


def test_extension_terms_are_found_and_marked(lookup):
    _, out, _ = lookup("rocket")
    assert "ZULU" in out and "(only with +expo)" in out
    _, out, _ = lookup("rocket", "-e", "expo")
    assert "ZULU" in out and "only with" not in out and "[+expo] Rocket" in out


def test_filters_apply_inside_the_definition(lookup):
    assert "ACTION-TEXT (normal)" in lookup("action card")[1]
    assert "ACTION-TEXT (quick)" in lookup("action card", "-v", "quick")[1]


def test_see_also(lookup):
    _, out, _ = lookup("comet")
    assert "COMET-TEXT" in out and "AFTER-HEADING" in out
    assert "see also: Rocket" in out


def test_component_without_definition(lookup):
    code, out, _ = lookup("expo card", "-e", "expo")
    assert code == 0 and "10x expo card — CHARLIE" in out and "4x rocket" in out


def test_too_many_matches(lookup):
    code, out, _ = lookup("c")
    assert code == 1 and "be more precise" in out


def test_no_match(lookup):
    code, _, err = lookup("xyzzy")
    assert code == 1 and "nothing called 'xyzzy'" in err


def test_list_all_terms(lookup):
    code, out, _ = lookup()
    assert code == 0 and "Glossary" in out and "Card" in out and "Rocket" not in out   # base game
    _, out, _ = lookup("--all")
    assert "Rocket" in out and "Comet" in out


def test_json(lookup):
    _, out, _ = lookup("rocket", "--json")
    data = json.loads(out)
    assert data["match"] == "exact"
    r = data["results"][0]
    assert r["term"] == "Rocket" and r["cond"] == "+expo" and r["in_selection"] is False


def test_section_by_role_or_title(lookup):
    code, out, _ = lookup("components")
    assert code == 0 and "ALPHA" in out and "DELTA" not in out
    code, out, _ = lookup("setup", "-p", "2")
    assert code == 0 and "DELTA" in out and "GOLF" in out and "HOTEL" not in out


def test_exact_term_beats_section(tmp_path, capsys):
    (tmp_path / "g").mkdir()
    (tmp_path / "g" / "g.game").write_text(
        "---\ntitle: G\nplayers: 2\n---\n# Setup {#setup}\n\nSETUP-SECTION\n\n# Glossary\n\n"
        "Setup\n: SETUP-TERM\n", encoding="utf-8")
    tabula.main(["--vault", str(tmp_path), "lookup", "g", "setup", "--no-color"])
    out = capsys.readouterr().out
    assert "SETUP-TERM" in out and "SETUP-SECTION" not in out
