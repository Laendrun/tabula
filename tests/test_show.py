"""`tabula show` on the kitchen-sink test game: filtering, highlighting, sections, languages, JSON."""
import tabula
import json


def has(out, *words):
    return all(w in out for w in words)


def lacks(out, *words):
    return not any(w in out for w in words)


# ---------------------------------------------------------------- default view: base game

def test_default_is_base_game(show):
    code, out, _ = show("kitchen-sink")
    assert code == 0
    assert "Showing: base game, no variants" in out
    assert has(out, "ALPHA", "DELTA", "NOVEMBER")
    assert lacks(out, "CHARLIE", "FOXTROT", "LIMA", "OSCAR", "ZULU", "COMET-TEXT")
    assert lacks(out, "4x rocket")                       # nested under a hidden extension component


def test_player_rules_stay_visible_with_badges_when_no_count_given(show):
    _, out, _ = show("kitchen-sink")
    assert "[2p] Two-player rules" in out
    assert "⟨2p: 9 | 3-4p: 7 | *: 5⟩" in out
    assert "[3-5p] SIERRA" in out


# ---------------------------------------------------------------- player counts

def test_two_players(show):
    _, out, _ = show("kitchen-sink", "-p", "2")
    assert has(out, "KILO", "GOLF", "Deal 9 cards", "2-3p")
    assert lacks(out, "HOTEL", "BRAVO", "SIERRA", "4-5p", "[2p]")


def test_four_players(show):
    _, out, _ = show("kitchen-sink", "-p", "4")
    assert has(out, "HOTEL", "BRAVO", "SIERRA", "Deal 7 cards", "4-5p")
    assert lacks(out, "KILO", "GOLF", "Two-player rules")   # empty section hidden


def test_five_players_uses_fallback_choice(show):
    _, out, _ = show("kitchen-sink", "-p", "5")
    assert "Deal 5 cards" in out


def test_numbered_steps_are_renumbered(show):
    _, out, _ = show("kitchen-sink", "-p", "2")
    assert "3. {2p}" not in out
    assert "3. Remove the action cards. GOLF" in out
    assert "5. JULIET" in out


def test_player_table_columns_and_rows(show):
    _, out, _ = show("kitchen-sink", "-p", "3")
    hand = [l for l in out.splitlines() if l.startswith("Hand size")][0]
    assert "3p" in hand and "2p" not in hand and "4-5p" not in hand
    assert "2-3p" in out and "4-5p     40" not in out


def test_content_nested_under_a_step_follows_it(show):
    _, out, _ = show("kitchen-sink", "-p", "2")
    assert "INDIA" in out
    assert "QUEBEC" in out


def test_out_of_range_players(show):
    code, _, err = show("kitchen-sink", "-p", "9")
    assert code == 2 and "not 9" in err


# ---------------------------------------------------------------- extensions and variants

def test_extension_adds_and_highlights(show):
    _, out, _ = show("kitchen-sink", "-e", "expo")
    assert has(out, "[+expo] 10x expo card — CHARLIE", "4x rocket", "[+expo] Shuffle in", "LIMA", "ZULU")
    assert "Showing: +expo" in out
    assert "base game" not in out


def test_variant_switches_alternatives(show):
    _, out, _ = show("kitchen-sink", "-v", "quick")
    assert "OSCAR" in out and "NOVEMBER" not in out
    assert "ACTION-TEXT (quick)" in out
    assert "Quick hand" in out


def test_without_variant_uses_the_other_alternative(show):
    _, out, _ = show("kitchen-sink")
    assert "ACTION-TEXT (normal)" in out
    assert "Quick hand" not in out


def test_all_shows_everything_with_badges(show):
    _, out, _ = show("kitchen-sink", "--all")
    assert has(out, "CHARLIE", "LIMA", "OSCAR", "NOVEMBER", "ZULU", "[+expo]", "[-quick]", "[2p]")


def test_all_conflicts_with_extensions(show):
    code, _, err = show("kitchen-sink", "--all", "-e", "expo")
    assert code == 2 and "--all" in err


def test_unknown_option(show):
    code, _, err = show("kitchen-sink", "-e", "nope")
    assert code == 2 and "nope" in err


# ---------------------------------------------------------------- markdown details

def test_escapes_and_code_blocks(show):
    _, out, _ = show("kitchen-sink")
    assert "TANGO is written with {escaped} braces and a [[literal]] bracket." in out
    assert "UNIFORM is code: {2p} [[not a ref]]" in out


def test_definitions(show):
    _, out, _ = show("kitchen-sink", "-e", "expo")
    assert has(out, "VICTOR", "WHISKEY", "XRAY", "YANKEE", "COMET-TEXT with a rocket reference", "AFTER-HEADING")
    assert "[+expo] Rocket" in out and "[+expo] Comet" in out   # condition before and after the term


def test_key_rules_and_images(show):
    _, out, _ = show("kitchen-sink")
    assert "★ MIKE" in out
    assert "[image: The box" in out


# ---------------------------------------------------------------- sections

def test_section_by_role(show):
    _, out, _ = show("kitchen-sink", "-s", "glossary")
    assert "VICTOR" in out and "DELTA" not in out and "ALPHA" not in out


def test_section_by_title_and_several(show):
    _, out, _ = show("kitchen-sink", "-s", "components", "-s", "play")
    assert has(out, "ALPHA", "MIKE") and lacks(out, "DELTA", "VICTOR")


def test_subsection_by_title(show):
    _, out, _ = show("kitchen-sink", "-p", "2", "-s", "two-player rules")
    assert "KILO" in out and "DELTA" not in out


def test_unknown_section(show):
    code, _, err = show("kitchen-sink", "-s", "nope")
    assert code == 2 and "#glossary" in err


# ---------------------------------------------------------------- languages

def test_translation(show):
    _, out, _ = show("kitchen-sink", "-l", "fr")
    assert has(out, "Évier de cuisine", "FR-ALPHA", "FR-VICTOR") and "ALPHA —" not in out


def test_missing_language_falls_back(show):
    code, out, err = show("kitchen-sink", "-l", "de")
    assert code == 0 and "ALPHA" in out and "no 'de' version" in err


# ---------------------------------------------------------------- json

def test_json(show):
    _, out, _ = show("kitchen-sink", "-p", "2", "-e", "expo", "--json")
    data = json.loads(out)
    comps = {c["name"]: c for c in data["components"]}
    assert comps["number card"]["part_of"] == "card"
    assert comps["rocket"]["added_by"] == ["expo"]
    assert "board" not in comps                                   # 4+ players only
    assert "MIKE is a key rule." in data["key_rules"]
    assert {"Card", "Rocket", "Comet"} <= {g["term"] for g in data["glossary"]}
    assert data["filters"] == {"players": 2, "options": ["expo"], "all": False}


def test_numbered_steps_count_from_the_list_start(tmp_path, capsys):
    (tmp_path / "g").mkdir()
    (tmp_path / "g" / "g.game").write_text(
        "---\ntitle: G\nplayers: 2-4\n---\n# Setup\n\n1. {2p} Two only.\n2. Shuffle.\n3. Deal.\n\n"
        "Text.\n\n3. Third.\n4. Fourth {2p}\n5. Fifth.\n", encoding="utf-8")
    tabula.main(["--vault", str(tmp_path), "show", "g", "-p", "3", "--no-color"])
    out = capsys.readouterr().out
    assert "1. Shuffle." in out and "2. Deal." in out                # the hidden step 1 isn't a gap
    assert "3. Third." in out and "4. Fifth." in out                 # a list may start at 3
    tabula.main(["--vault", str(tmp_path), "export", "g", "-p", "3", "-o", "-"])
    html = capsys.readouterr().out
    assert 'value="1">Shuffle.' in html and 'value="4">Fifth.' in html
