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


def test_game_links_only_take_a_games_file_name(tmp_path, capsys):
    body = ("[a](game:javascript:alert(1);//) [b](game:../../x) [c](game:Hearts) [ok](game:crazy-eights)\n\n"
            "[d](//evil.example/x) [e](\\\\evil\\x) [f](/\\evil) [rel](./a.html) [root](/rules.html)\n")
    root = vault(tmp_path, body)
    _, out, _ = run(capsys, root, "export", "g", "-o", "-")
    assert "javascript:" not in out.split("<body", 1)[1].replace("javascript:alert(1);//)", "")
    assert 'href="crazy-eights.html"' in out and 'href="./a.html"' in out and 'href="/rules.html"' in out
    for bad in ('href="../../x', 'href="Hearts', 'href="//evil', 'href="\\\\evil', 'href="/\\evil'):
        assert bad not in out, bad
    run(capsys, root, "book", "-o", str(tmp_path / "b.epub"))
    import zipfile
    page = zipfile.ZipFile(tmp_path / "b.epub").read("OEBPS/g.xhtml").decode()
    assert 'href="javascript' not in page
    _, out, _ = run(capsys, root, "check", "--no-color")
    assert out.count("is not a game's file name") == 3 and out.count("leads to another site") == 3


def test_an_automatic_cover_linking_outside_the_vault_is_not_used(tmp_path, capsys):
    root = vault(tmp_path, "Text.\n")
    (root / "g" / "media" / "g_cover.png").symlink_to(tmp_path / "secret.png")
    run(capsys, root, "site", "-o", str(tmp_path / "site"))
    assert not list((tmp_path / "site" / "g").glob("cover.*"))
    assert not any(leaked(f.read_bytes().decode("latin-1")) for f in (tmp_path / "site").rglob("*") if f.is_file())
    _, out, _ = run(capsys, root, "check", "--no-color")
    assert "cover image media/g_cover.png leads outside the vault" in out


def test_fragments_including_each_other_many_times_dont_hang(tmp_path, capsys):
    import time
    filler = "\n".join(f"Line {i}." for i in range(300))
    files = {f"_shared/f{i}.game": f"# F{i}\n\n{filler}\n\n" + ("" if i == 6 else "\n\n".join([f"![[f{i + 1}]]"] * 10))
             for i in range(7)}
    root = vault(tmp_path, "![[f0]]\n", files=files)
    start = time.monotonic()
    _, out, _ = run(capsys, root, "check", "--no-color")
    run(capsys, root, "export", "g", "-o", "-")
    assert time.monotonic() - start < 20
    assert "the fragments add more than 20000 lines" in out


def test_yaml_aliases_are_refused(tmp_path, capsys):
    aliases = "a0: &a0 [x, x, x, x, x, x, x, x, x, x]\n" + "".join(
        f"a{i}: &a{i} [{', '.join([f'*a{i - 1}'] * 10)}]\n" for i in range(1, 9))
    root = vault(tmp_path, "Text.\n", aliases)
    _, out, _ = run(capsys, root, "check", "--no-color")
    assert "aliases (*name) aren't allowed" in out
    code, out, _ = run(capsys, root, "show", "g", "--no-color")
    assert code == 0


def test_huge_rounds_and_player_counts_in_sheets(tmp_path, capsys):
    root = vault(tmp_path, "Text.\n", files={"g/score.sheet": "---\ngame: g\nrounds: 99999999\n---\n| | {player} |\n|-|-|\n| {r} | |\n"})
    (root / "g" / "g.game").write_text("---\ntitle: G\nplayers: 2-99999999\n---\n# Rules\n\nText.\n", encoding="utf-8")
    sheet = str(root / "g" / "score.sheet")
    code, out, _ = run(capsys, root, "sheet", sheet, "-o", "-")
    assert code == 0 and out.count("<tr") < 200
    _, out, _ = run(capsys, root, "check", "--no-color")
    assert "a sheet has at most 100 rounds" in out
    with pytest.raises(SystemExit, match="at most 100 player columns"):
        run(capsys, root, "sheet", sheet, "-p", "99999999", "-o", "-")


def test_book_language_must_be_a_code(tmp_path, capsys):
    code, _, err = run(capsys, vault(tmp_path, "Text.\n"), "book", "-l", 'en"><x', "-o", str(tmp_path / "b.epub"))
    assert code == 2 and "not a language code" in err and not (tmp_path / "b.epub").exists()


def test_add_word_takes_one_word(tmp_path):
    from tabula.editor import add_word
    with pytest.raises(ValueError):
        add_word(tmp_path, "two\nlines")
    with pytest.raises(ValueError):
        add_word(tmp_path, "a # comment")
    add_word(tmp_path, "meeple")
    assert (tmp_path / "words.txt").read_text(encoding="utf-8").splitlines()[-1] == "meeple"
