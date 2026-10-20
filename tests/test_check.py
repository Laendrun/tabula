"""`tabula check`: clean files stay clean, and each kind of mistake is reported."""
import pytest

import tabula
from conftest import EXAMPLES, FIXTURES


def check_vault(path, require_defs=False):
    vault = tabula.Vault(path)
    issues = list(vault.issues)
    for p in vault.discover():
        game = vault.load(p)
        issues += tabula.check_game(game, vault, require_defs=require_defs)
        for lang in game.languages:
            if lang != game.default_language:
                issues += tabula.check_translation(game, vault.load(p, lang), vault)
    return issues


def test_fixture_vault_is_clean():
    assert check_vault(FIXTURES) == []


def test_example_vault_is_clean():
    assert check_vault(EXAMPLES) == []


def test_minimal_game_is_clean(check_body):
    assert check_body("# Rules\n\n- 1x [[deck]]\n\nShuffle the [[deck]].\n") == []


@pytest.mark.parametrize("body, expected", [
    ("{+nope} text\n", "error: '+nope' is not declared"),
    ("{9p} text\n", "never applies"),
    ("Deal {2p} cards here.\n", "in the middle of text"),
    ("{2 p} text\n", "invalid condition"),
    ("Deal {3p: 5 | 4p 6} cards.\n", "invalid condition"),
    ("{*} text\n", "'*' (otherwise) only works inside an inline choice"),
    ("Use the [[pawn]].\n", "[[pawn]] matches no component"),
    ("- 1x [[deck]]\n\nTake the [deck].\n", "has single brackets"),
    ("Take the [[deck.\n", "unclosed '[['"),
    ("[[Term]]\n: text\n", "written as a reference"),
    ("Term\n: one\n\nTerm\n: two\n", "defined twice"),
    ("Term\n:\n\nNext\n", "is empty"),
    ("![x](media/none.png)\n", "image not found"),
    ("| A | 2p | three |\n|---|---|---|\n| x | 1 | 2 |\n", "mixes player codes"),
    ("| Players | short |\n|---|---|\n| 2-4 | 9 |\n", "looks like player counts"),
    ("# Title {+}\n", "invalid heading attributes"),
    ("<!-- never closed\n", "unclosed comment"),
    ("= Old heading\n", "headings use '#'"),
    ("Take the @token.\n", "old '@component'"),
    ("[p=2] old\n", "old '[p=…]'"),
    ("+++ rules\n", "'+++ rules' is no longer used"),
])
def test_mistakes_are_reported(check_body, body, expected):
    messages = check_body(body)
    assert any(expected in m for m in messages), messages


@pytest.mark.parametrize("meta, expected", [
    ("players: 2-4", "missing required 'title'"),
    ("title: T", "missing required 'players'"),
    ("title: T\nplayers: lots", "invalid players"),
    ("title: T\nplayers: 2-4\ncover: media/nope.jpg", "cover image not found"),
    ("title: T\nplayers: 2-4\nvariants: 3", "'variants' must be"),
    ("title: T\nplayers: 2-4\nvariants: [x]\nextensions: [x]", "both as a variant and as an extension"),
])
def test_frontmatter_problems(check_body, meta, expected):
    messages = check_body("text\n", meta=meta)
    assert any(expected in m for m in messages), messages


def test_condition_at_the_end_of_a_line_is_fine(check_body):
    assert check_body("- 1x [[deck]] {2p}\n\nShuffle. {3-4p}\n") == []


def test_require_definitions(check_body):
    body = "- 1x [[deck]]\n- 1x [[pawn]]\n\nPawn\n: A pawn.\n"
    assert check_body(body) == []
    messages = check_body(body, require_defs=True)
    assert len(messages) == 1 and "'deck' has no definition" in messages[0]


def test_translation_problems(tmp_path):
    (tmp_path / "g").mkdir()
    (tmp_path / "g" / "g.game").write_text("---\ntitle: G\nplayers: 2-4\n---\ntext\n", encoding="utf-8")
    (tmp_path / "g" / "g.fr.game").write_text(
        "---\ntitle: J\nplayers: 3-5\nlanguage: de\nvariants: {extra: x}\n---\ntexte\n", encoding="utf-8")
    vault = tabula.Vault(tmp_path)
    p = vault.find("g")
    msgs = [i.msg for i in tabula.check_translation(vault.load(p), vault.load(p, "fr"), vault)]
    assert any("'players' differs" in m for m in msgs)
    assert any("doesn't match the file name" in m for m in msgs)
    assert any("not declared in the default language" in m for m in msgs)


def test_vault_layout_problems(tmp_path):
    (tmp_path / "a").mkdir()
    (tmp_path / "a" / "b.game").write_text("---\ntitle: B\nplayers: 2\n---\n", encoding="utf-8")
    (tmp_path / "solo.de.game").write_text("---\ntitle: S\nplayers: 2\n---\n", encoding="utf-8")
    vault = tabula.Vault(tmp_path)
    vault.discover()
    msgs = [i.msg for i in vault.issues]
    assert any("should be named 'a.game'" in m for m in msgs)
    assert any("translation without the default-language file" in m for m in msgs)
