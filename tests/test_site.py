"""`tabula site`: the whole vault as a static website."""
import re
from pathlib import Path

import pytest

import tabula
from conftest import EXAMPLES, FIXTURES


def build(vault, out, capsys=None):
    code = tabula.main(["--vault", str(vault), "site", "-o", str(out)])
    if capsys:
        capsys.readouterr()
    return code


def test_pages_for_every_game_language_and_cheat_sheet(tmp_path, capsys):
    out = tmp_path / "site"
    assert build(FIXTURES, out, capsys) == 0
    files = {str(p.relative_to(out)) for p in out.rglob("*") if p.is_file()}
    assert {"index.html", "kitchen-sink/index.html", "kitchen-sink/index.fr.html",
            "kitchen-sink/key.html", "kitchen-sink/cover.png"} <= files


def test_index_lists_games_with_filter_data(tmp_path, capsys):
    out = tmp_path / "site"
    build(FIXTURES, out, capsys)
    index = (out / "index.html").read_text(encoding="utf-8")
    assert "<title>Test vault</title>" in index
    card = re.search(r'<li class="game-card"[^>]*>', index).group(0)
    assert 'data-players="2 3 4 5"' in card and 'data-dmax="40"' in card and 'data-tags="card"' in card
    assert 'href="kitchen-sink/index.html"' in index and 'href="kitchen-sink/key.html"' in index
    assert 'href="kitchen-sink/index.fr.html" hreflang="fr"' in index
    assert 'src="kitchen-sink/cover.png"' in index


def test_game_pages_have_navigation_in_their_language(tmp_path, capsys):
    out = tmp_path / "site"
    build(FIXTURES, out, capsys)
    en = (out / "kitchen-sink" / "index.html").read_text(encoding="utf-8")
    fr = (out / "kitchen-sink" / "index.fr.html").read_text(encoding="utf-8")
    key = (out / "kitchen-sink" / "key.html").read_text(encoding="utf-8")
    assert '<a href="../index.html">← All games</a>' in en and 'href="key.html">Key rules</a>' in en
    assert "← Tous les jeux" in fr and 'href="index.html" hreflang="en">EN</a>' in fr
    assert "MIKE" in key and "DELTA" not in key            # the cheat sheet has only the key rules
    assert "CHARLIE" in en                                 # rule pages show everything, extensions included


def test_every_internal_link_points_to_a_file(tmp_path, capsys):
    for vault in (FIXTURES, EXAMPLES):
        out = tmp_path / vault.parent.name
        assert build(vault, out, capsys) == 0
        for page in out.rglob("*.html"):
            for href in re.findall(r'(?:href|src)="([^"]+)"', page.read_text(encoding="utf-8")):
                if href.startswith(("#", "http://", "https://", "data:", "mailto:")):
                    continue
                target = (page.parent / href.split("#")[0]).resolve()
                assert target.exists(), f"{page.relative_to(out)} links to missing {href}"


def test_links_to_other_games(tmp_path, capsys):
    vault = tmp_path / "vault"
    for slug, body in (("a", "See [game B](game:b)."), ("b", "Hello.")):
        (vault / slug).mkdir(parents=True)
        (vault / slug / f"{slug}.game").write_text(f"---\ntitle: {slug.upper()}\nplayers: 2\n---\n# Rules\n\n{body}\n",
                                                   encoding="utf-8")
    build(vault, tmp_path / "site", capsys)
    assert '<a href="../b/index.html">game B</a>' in (tmp_path / "site" / "a" / "index.html").read_text()


def test_replaces_its_own_folder_but_not_others(tmp_path, capsys):
    out = tmp_path / "site"
    build(FIXTURES, out, capsys)
    (out / "stale.html").write_text("old")
    build(FIXTURES, out, capsys)
    assert not (out / "stale.html").exists() and (out / "index.html").exists()

    other = tmp_path / "documents"
    other.mkdir()
    (other / "thesis.txt").write_text("precious")
    with pytest.raises(SystemExit, match="wasn't made by 'tabula site'"):
        build(FIXTURES, other)
    assert (other / "thesis.txt").read_text() == "precious"


def test_refuses_the_vault_folder(tmp_path):
    vault = tmp_path / "vault"
    (vault / "g").mkdir(parents=True)
    (vault / "g" / "g.game").write_text("---\ntitle: G\nplayers: 2\n---\n# A\n\nB.\n", encoding="utf-8")
    with pytest.raises(SystemExit, match="can't be the vault"):
        build(vault, vault)


def test_empty_vault(tmp_path, capsys):
    (tmp_path / "vault").mkdir()
    assert build(tmp_path / "vault", tmp_path / "site") == 1
    assert "no games" in capsys.readouterr().err
    assert not (tmp_path / "site").exists()
