"""`tabula check --json` and `--stdin`: what the VS Code extension uses."""
import io
import json
import sys

import pytest

import tabula


def vault(tmp_path, body="# Rules\n\nUse the [[deck]].\n\n- 1x [[deck]]\n"):
    (tmp_path / "g").mkdir(exist_ok=True)
    f = tmp_path / "g" / "g.game"
    f.write_text(f"---\ntitle: G\nplayers: 2\n---\n{body}", encoding="utf-8")
    return f


def check(capsys, *args, stdin=None, monkeypatch=None):
    if stdin is not None:
        monkeypatch.setattr(sys, "stdin", io.TextIOWrapper(io.BytesIO(stdin.encode("utf-8")), encoding="utf-8"))
    code = tabula.main(["check", *args])
    return code, json.loads(capsys.readouterr().out)


def test_json_lists_issues_with_absolute_paths(tmp_path, capsys):
    f = vault(tmp_path, "# Rules\n\nSee [[nowhere]].\n")
    code, data = check(capsys, str(f), "--json")
    assert code == 0                                       # a warning only
    (issue,) = data["issues"]
    assert issue == {"path": str(f.resolve()), "line": 7, "level": "warning", "message": issue["message"]}
    assert "[[nowhere]]" in issue["message"]
    assert data["files"] == [str(f.resolve())]


def test_json_exit_code_on_errors(tmp_path, capsys):
    f = vault(tmp_path, "# Rules\n\nSee [[open\n")
    code, data = check(capsys, str(f), "--json")
    assert code == 1 and data["issues"][0]["level"] == "error"


def test_stdin_replaces_the_file_on_disk(tmp_path, capsys, monkeypatch):
    f = vault(tmp_path)                                    # clean on disk
    text = "---\r\ntitle: G\r\nplayers: 2\r\n---\r\n# Règles\r\n\r\nVoir [[ailleurs]].\r\n"   # CRLF, accents
    code, data = check(capsys, str(f), "--json", "--stdin", stdin=text, monkeypatch=monkeypatch)
    assert [i["line"] for i in data["issues"]] == [7]
    assert "ailleurs" in data["issues"][0]["message"]
    assert "ailleurs" not in f.read_text(encoding="utf-8")   # nothing written


def test_stdin_for_a_translation_file(tmp_path, capsys, monkeypatch):
    f = vault(tmp_path)
    fr = f.with_name("g.fr.game")
    fr.write_text("---\ntitle: G\n---\n# Règles\n\nLe [[deck]].\n", encoding="utf-8")
    code, data = check(capsys, str(fr), "--json", "--stdin", monkeypatch=monkeypatch,
                       stdin="---\ntitle: G\n---\n# Règles\n\nLe [[paquet]].\n")
    assert str(fr.resolve()) in data["files"]
    assert [(i["path"], i["line"]) for i in data["issues"]] == [(str(fr.resolve()), 6)]


def test_stdin_needs_one_file(tmp_path, capsys):
    vault(tmp_path)
    with pytest.raises(SystemExit, match="exactly one"):
        tabula.main(["--vault", str(tmp_path), "check", "--stdin"])
