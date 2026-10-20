"""TODO reminders (`<!-- TODO: … -->`, `tabula todo`) and definitions nothing refers to."""
import io
import json
import sys

import tabula


def vault(tmp_path, body, meta="title: G\nplayers: 2", files=None, config=None):
    (tmp_path / "g").mkdir(parents=True, exist_ok=True)
    (tmp_path / "g" / "g.game").write_text(f"---\n{meta}\n---\n{body}", encoding="utf-8")
    for name, text in (files or {}).items():
        (tmp_path / "g" / name).write_text(text, encoding="utf-8")
    if config:
        (tmp_path / "vault.yaml").write_text(config, encoding="utf-8")
    return tmp_path


def run(capsys, v, *args):
    code = tabula.main(["--vault", str(v), *args])
    out = capsys.readouterr()
    return code, out.out, out.err


TODOS = """# Rules

Play. <!-- TODO: check the 5-player setup -->

<!--
  fixme: count the
  cards again
-->

<!-- a normal comment -->

- 1x [[deck]]
"""


# ------------------------------------------------------------------ TODO

def test_todo_lists_reminders_with_lines(tmp_path, capsys):
    v = vault(tmp_path, TODOS, files={"g.fr.game": "---\ntitle: G\n---\n# Règles\n\n<!-- TODO traduire -->\n"})
    code, out, _ = run(capsys, v, "todo", "--no-color")
    assert code == 0
    assert "g.game:7  check the 5-player setup" in out
    assert "g.game:9  count the cards again" in out            # multi-line, case-insensitive FIXME
    assert "g.fr.game:6  traduire" in out                       # translations too
    assert "normal comment" not in out
    assert "3 TODO(s) in 1 game(s)" in out


def test_todo_json_and_nothing_to_do(tmp_path, capsys):
    v = vault(tmp_path, TODOS)
    _, out, _ = run(capsys, v, "todo", "--json")
    data = json.loads(out)
    assert [(t["line"], t["text"]) for t in data] == [(7, "check the 5-player setup"), (9, "count the cards again")]
    v2 = vault(tmp_path / "other", "# Rules\n\nDone.\n")
    assert run(capsys, v2, "todo")[1].strip() == "no TODOs"


def test_check_counts_todos_but_they_are_not_warnings(tmp_path, capsys):
    v = vault(tmp_path, TODOS)
    code, out, _ = run(capsys, v, "check", "--no-color", "--strict")
    assert code == 0                                            # --strict fails on warnings, not on TODOs
    assert "ok  (2 TODO)" in out and "0 warning(s), 2 TODO (tabula todo)" in out
    assert "check the 5-player setup" not in out                # listed by `tabula todo`, not by check


def test_check_json_reports_todos_for_editors(tmp_path, capsys, monkeypatch):
    v = vault(tmp_path, "# Rules\n\nDone.\n")
    unsaved = "---\ntitle: G\nplayers: 2\n---\n# Rules\n\n<!-- TODO: unsaved reminder -->\n"
    monkeypatch.setattr(sys, "stdin", io.TextIOWrapper(io.BytesIO(unsaved.encode()), encoding="utf-8"))
    code, out, _ = run(capsys, v, "check", str(v / "g" / "g.game"), "--json", "--stdin", "--strict")
    issues = json.loads(out)["issues"]
    assert code == 0 and [(i["level"], i["line"], i["message"]) for i in issues] == [
        ("todo", 7, "TODO: unsaved reminder")]


# ------------------------------------------------------------------ unused definitions

UNUSED = """# Components

- 2x [[pawn]]

# Rules

Move your [[pawns]]. See [[#Glossary]]. Watch the [[Trap|traps]].

# Glossary

Pawn
: A piece.

Trap
: A square. Unlike the [[Bridge]].

Bridge
: Mentioned in another definition only.

Forgotten
: Nothing links here.

## Cards {#cards}

Ace
: points:: 1
  Cards in a catalog don't need a link.
"""


def test_unused_definitions_are_reported(tmp_path, capsys):
    code, out, _ = run(capsys, vault(tmp_path, UNUSED), "check", "--no-color")
    assert code == 0                                            # a warning, not an error
    assert out.count("is defined but nothing refers to it") == 1
    assert "'Forgotten' is defined but nothing refers to it; link to it with [[Forgotten]]" in out


def test_section_links_do_not_count_as_references(tmp_path, capsys):
    body = "# Rules\n\nSee [[#Glossary]].\n\n# Glossary\n\nGlossary\n: A term with a section's name.\n"
    _, out, _ = run(capsys, vault(tmp_path, body), "check", "--no-color")
    assert "'Glossary' is defined but nothing refers to it" in out


def test_unused_check_can_be_turned_off(tmp_path, capsys):
    off = run(capsys, vault(tmp_path / "a", UNUSED, meta="title: G\nplayers: 2\nunused_definitions: false"),
              "check", "--no-color")[1]
    assert "nothing refers to it" not in off
    off = run(capsys, vault(tmp_path / "b", UNUSED, config="check:\n  unused_definitions: false\n"),
              "check", "--no-color")[1]
    assert "nothing refers to it" not in off
    on = run(capsys, vault(tmp_path / "c", UNUSED, meta="title: G\nplayers: 2\nunused_definitions: true",
                           config="check:\n  unused_definitions: false\n"), "check", "--no-color")[1]
    assert "nothing refers to it" in on                         # the game's frontmatter wins over vault.yaml


def test_translations_are_checked_on_their_own(tmp_path, capsys):
    fr = "---\ntitle: G\n---\n# Règles\n\nUn [[pion]].\n\n# Lexique\n\nPion\n: Une pièce.\n\nOublié\n: Rien.\n"
    _, out, _ = run(capsys, vault(tmp_path, UNUSED, files={"g.fr.game": fr}), "check", "--no-color")
    assert "g.fr.game:13  'Oublié' is defined but nothing refers to it" in out
