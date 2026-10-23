"""A vault someone shares can't make tabula publish other files, run scripts in the pages, or hang it."""
import base64

import pytest

import tabula

SECRET = "TOP-SECRET-KEY-1234"


def vault(tmp_path, body="", meta="", files=None):
    root = tmp_path / "v"
    (root / "g" / "media").mkdir(parents=True)
    (root / "g" / "media" / "ok.png").write_bytes(b"\x89PNG fine")
    (tmp_path / "secret.png").write_text(SECRET, encoding="utf-8")       # outside the vault
    (root / "g" / "g.game").write_text(f"---\ntitle: G\nplayers: 2\n{meta}---\n# Rules\n\n{body}", encoding="utf-8")
    for name, text in (files or {}).items():
        (root / name).parent.mkdir(parents=True, exist_ok=True)
        (root / name).write_text(text, encoding="utf-8")
    return root


def run(capsys, root, *args):
    code = tabula.main(["--vault", str(root), *args])
    o = capsys.readouterr()
    return code, o.out, o.err


def leaked(text):
    return SECRET in text or base64.b64encode(SECRET.encode()).decode()[:16] in text


@pytest.mark.parametrize("src", ["../../secret.png", "{abs}"])
def test_files_outside_the_vault_are_never_embedded(tmp_path, capsys, src):
    src = src.format(abs=tmp_path / "secret.png")
    body = (f"![x]({src})\n\n![ok](media/ok.png)\n\n# Glossary {{#glossary}}\n\n## Cards {{#cards}}\n\n"
            f"Card\n: image:: {src}\n  Text.\n")
    root = vault(tmp_path, body, f"cover: {src}\nsymbols:\n  s: {src}\n")
    for args in (["export", "g", "-o", "-"], ["export", "g", "--interactive", "-o", "-"]):
        _, out, _ = run(capsys, root, *args)
        assert not leaked(out)
        assert "data:image/png;base64," in out                  # a picture inside the vault still is
    run(capsys, root, "site", "-o", str(tmp_path / "site"))
    for f in (tmp_path / "site").rglob("*"):
        if f.is_file():
            assert not leaked(f.read_text(encoding="utf-8", errors="replace")), f
    _, out, _ = run(capsys, root, "check", "--no-color")
    assert out.count("outside the vault") >= 4               # image, picture, cover, symbol


def test_links_that_run_scripts_are_not_links(tmp_path, capsys):
    body = ("[a](javascript:alert(1)) [b]( JavaScript:alert(1)) [c](data:text/html,x) [d](vbscript:x)\n\n"
            "[ok](https://example.com) [rel](other.html#x) [mail](mailto:a@b.c) [game](game:hearts)\n")
    _, out, _ = run(capsys, vault(tmp_path, body), "export", "g", "-o", "-")
    for bad in ("javascript:", "JavaScript:", "data:text/html", "vbscript:"):
        assert f'href="{bad}' not in out and f'href=" {bad}' not in out
    for good in ('href="https://example.com"', 'href="other.html#x"', 'href="mailto:a@b.c"'):
        assert good in out
    root = vault(tmp_path / "w", files={"wishlist.yaml": "- name: X\n  link: javascript:alert(1)\n- name: Y\n  link: https://shop.ch\n"})
    run(capsys, root, "site", "-o", str(tmp_path / "site"))
    page = (tmp_path / "site" / "wishlist.html").read_text(encoding="utf-8")
    assert "javascript:" not in page and 'href="https://shop.ch"' in page


def test_language_must_be_a_code(tmp_path, capsys):
    root = vault(tmp_path, "Text.\n", 'language: "fr\\"><script>alert(1)</script>"\n')
    run(capsys, root, "site", "-o", str(tmp_path / "site"))
    for f in (tmp_path / "site").rglob("*.html"):
        assert "<script>alert" not in f.read_text(encoding="utf-8")
    assert all(p.resolve().is_relative_to((tmp_path / "site").resolve()) for p in (tmp_path / "site").rglob("*"))
    _, out, _ = run(capsys, root, "check", "--no-color")
    assert "is not a language code" in out


def test_a_nul_character_doesnt_hang(tmp_path, capsys):
    root = vault(tmp_path, "Draw a\x00card \x000\x00 [[x]] {2p: a | *: b}.\n")
    code, out, _ = run(capsys, root, "export", "g", "-o", "-")          # used to loop forever
    assert code == 0 and "Draw acard" in out
    _, out, _ = run(capsys, root, "check", "--no-color")
    assert "NUL character" in out


def test_fmt_leaves_other_encodings_alone(tmp_path, capsys):
    root = vault(tmp_path)
    latin = "---\ntitle: Jeu\nplayers: 2\n---\n# Règles\n\n\n\nÉté.\n".encode("latin-1")
    (root / "g" / "g.game").write_bytes(latin)
    code, out, _ = run(capsys, root, "fmt")
    assert code == 1 and "not UTF-8" in out
    assert (root / "g" / "g.game").read_bytes() == latin                 # untouched: the accents are still there
    _, out, _ = run(capsys, root, "check", "--no-color")
    assert "isn't UTF-8" in out


def test_includes_stay_in_shared(tmp_path, capsys):
    (tmp_path / "evil.game").write_text(f"# S\n\n{SECRET}\n", encoding="utf-8")
    root = vault(tmp_path, "![[../../evil]]\n\n![[../evil]]\n")
    _, out, _ = run(capsys, root, "export", "g", "-o", "-")
    assert SECRET not in out
    _, out, _ = run(capsys, root, "check", "--no-color")
    assert "no shared fragment '../../evil'" in out


def test_new_refuses_paths(tmp_path, capsys):
    root = vault(tmp_path)
    for slug in ("../x", "a/b", ".hidden"):
        with pytest.raises(SystemExit):
            tabula.main(["--vault", str(root), "new", slug])
    assert not (tmp_path / "x").exists()
