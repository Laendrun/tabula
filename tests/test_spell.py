"""`tabula check --spell`, and the frontmatter key / role typo warnings."""
import json

import pytest

import tabula
from tabula import spell

pytest.importorskip("spylls")

EN = ["the", "a", "card", "cards", "draw", "draws", "discard", "player", "players", "play", "turn", "each", "one", "two",
      "in", "of", "on", "your", "is", "and", "with", "first", "setup", "rules", "glossary", "effect"]
FR = ["la", "le", "carte", "cartes", "joueur", "piochez", "tour", "œil", "coup", "un", "d", "règles"]


@pytest.fixture
def dicts(tmp_path, monkeypatch):
    """Tiny Hunspell dictionaries in a private cache folder, and no downloads."""
    cache = tmp_path / "cache"
    folder = cache / "dictionaries"
    folder.mkdir(parents=True)
    for lang, words in (("en", EN), ("fr", FR), ("en-gb", ["colour", "centre"])):
        (folder / f"{lang}.aff").write_text("SET UTF-8\nWORDCHARS '\n", encoding="utf-8")
        (folder / f"{lang}.dic").write_text(f"{len(words)}\n" + "\n".join(words) + "\n", encoding="utf-8")
    monkeypatch.setenv("TABULA_CACHE", str(cache))
    monkeypatch.setattr(spell, "_loaded", {})

    def no_download(lang, folder):
        raise spell.SpellError(f"no '{lang}' spelling dictionary (test)")
    monkeypatch.setattr(spell, "download", no_download)
    import tabula.check as check
    monkeypatch.setattr(check, "_spell_failed", set())
    return folder


def vault(tmp_path, body, meta="", extra=None):
    root = tmp_path / "v"
    (root / "g").mkdir(parents=True, exist_ok=True)
    (root / "g" / "g.game").write_text(f"---\ntitle: Gizmo Party\nplayers: 2-4\n{meta}---\n{body}", encoding="utf-8")
    for name, text in (extra or {}).items():
        (root / name).parent.mkdir(parents=True, exist_ok=True)
        (root / name).write_text(text, encoding="utf-8")
    return root


def check(capsys, root, *args):
    code = tabula.main(["--vault", str(root), "check", "--no-color", *args])
    return code, capsys.readouterr().out


def words(out):
    return [line.split("unknown word ")[1].split("'")[1] for line in out.splitlines() if "unknown word '" in line]


def test_unknown_words(tmp_path, dicts, capsys):
    body = ("# Rules\n\n"
            "Each player draws one crad.\n"                                  # 6: a typo
            "Discard a [[Zorblax]] and [[Zorblax|the zorblaks]].\n"          # 7: refs skipped, alias checked
            "{2p} Draw two cards. {3p: Draw one | *: Discadr two}\n"         # 8: conditions skipped, choices checked
            "Play `qwzx` on https://exampel.com/plaay <b>the</b> [card](wrongg.html).\n"   # 9
            "<!-- TODO: frobnicate -->\n"                                    # 10: comments skipped
            "```\nzzzz yyyy\n```\n"
            "The 1st turn, THE GLOSSARY.\n\n"                                # ordinals and capitals skipped
            "# Glossary {#glossary}\n\nZorblax\n: effect:: Discard each card.\n")
    code, out = check(capsys, vault(tmp_path, body), "--spell")
    assert code == 0
    assert "g/g.game:7  unknown word 'crad'" in out
    assert words(out) == ["crad", "zorblaks", "Discadr"]
    assert "1 unknown word" not in out and "3 unknown word(s)" in out


def test_known_words(tmp_path, dicts, capsys):
    body = "# Rules\n\nThe Gizmo of Wobble and Plink, with Quux, on Zap. Fizzbo.\n\n- 3x [[Wobble token]]\n"
    meta = "designer: [Ann Plink]\nextensions: [quux]\nwords: [Fizzbo]\n"
    root = vault(tmp_path, body, meta, {"words.txt": "# names\nZap\n"})
    _, out = check(capsys, root, "--spell")
    assert words(out) == []


def test_did_you_mean_a_game_word(tmp_path, dicts, capsys):
    body = "# Rules\n\nDraw a Zorblaxx.\n\n# Glossary\n\nZorblax\n: A card.\n"
    _, out = check(capsys, vault(tmp_path, body), "--spell")
    assert "unknown word 'Zorblaxx' (did you mean 'zorblax'?)" in out


def test_spelling_is_not_a_warning(tmp_path, dicts, capsys):
    root = vault(tmp_path, "# Rules\n\nDraw a crad.\n")
    code, out = check(capsys, root, "--spell", "--strict")
    assert code == 0 and "0 warning(s), 1 unknown word(s)" in out
    tabula.main(["--vault", str(root), "check", "--json", "--spell"])
    data = json.loads(capsys.readouterr().out)
    assert [(i["level"], i["line"]) for i in data["issues"]] == [("spelling", 7)]


def test_turned_on_in_vault_yaml_off_in_frontmatter(tmp_path, dicts, capsys):
    root = vault(tmp_path, "# Rules\n\nDraw a crad.\n", extra={"vault.yaml": "check:\n  spelling: true\n"})
    assert words(check(capsys, root)[1]) == ["crad"]
    assert words(check(capsys, vault(tmp_path, "# Rules\n\nDraw a crad.\n", "spelling: false\n"))[1]) == []
    assert words(check(capsys, vault(tmp_path, "# Rules\n\nDraw a crad.\n", "spelling: false\n"), "-s")[1]) == []


def test_off_by_default(tmp_path, dicts, capsys):
    assert words(check(capsys, vault(tmp_path, "# Rules\n\nDraw a crad.\n"))[1]) == []


def test_each_language_its_dictionary(tmp_path, dicts, capsys):
    root = vault(tmp_path, "# Rules\n\nDraw a card.\n",
                 extra={"g/g.fr.game": "---\ntitle: Gizmo\n---\n# Règles\n\nPiochez la carte, coup d'oeil, "
                                       "un tuor.\n"})
    _, out = check(capsys, root, "--spell")
    assert "g/g.fr.game:6  unknown word 'tuor'" in out and words(out) == ["tuor"]   # oeil = œil


def test_missing_dictionary_is_one_warning(tmp_path, dicts, capsys):
    root = vault(tmp_path, "# Rules\n\nText.\n", "language: de\n")
    (root / "h").mkdir()
    (root / "h" / "h.game").write_text("---\ntitle: H\nplayers: 2\nlanguage: de\n---\n# Regeln\n", encoding="utf-8")
    code, out = check(capsys, root, "--spell")
    assert code == 0 and out.count("spell check: no 'de' spelling dictionary") == 1


def test_frontmatter_key_typos(tmp_path, capsys):
    root = vault(tmp_path, "# Rules\n\nPlay.\n", "durantion: 10\nseries: Micro\nrequire_definition: true\n")
    _, out = check(capsys, root)
    assert "'durantion:' in frontmatter: did you mean 'duration'?" in out
    assert "'require_definition:' in frontmatter: did you mean 'require_definitions'?" in out
    assert "series" not in out                    # your own keys are fine


def test_role_typos(tmp_path, capsys):
    body = "# Rules {#play}\n\n## Cartes {#cartes}\n\nX\n: Y.\n\n## Mine {#strategy}\n\nZ.\n"
    _, out = check(capsys, vault(tmp_path, body, "unused_definitions: false\n"))
    assert "g/g.game:8  role '#cartes': did you mean '#cards'?" in out
    assert "strategy" not in out


def test_english_accepts_british_spellings(tmp_path, dicts, capsys):
    _, out = check(capsys, vault(tmp_path, "# Rules\n\nThe colour of the centre card, the colr.\n"), "--spell")
    assert words(out) == ["colr"]


def test_paths_and_pictures_are_skipped(tmp_path, dicts, capsys):
    body = ("# Rules\n\nDraw media/cards/zorb.png and rulez.pdf.\n\n# Glossary {#glossary}\n\n## Cards {#cards}\n\n"
            "Card\n: image:: media/cardz/cardd.png\n  Draw a card.\n")
    _, out = check(capsys, vault(tmp_path, body), "--spell")
    assert words(out) == []
