"""The cover: `cover:` in the frontmatter, else media/cover.* or media/<slug>_cover.* found by its name."""
import json

import pytest

import tabula


def make(tmp_path, cover_line="", files=(), standalone=False):
    meta = f"---\ntitle: G\nplayers: 2\n{cover_line}---\n# Rules\n\nPlay.\n"
    tmp_path.mkdir(parents=True, exist_ok=True)
    if standalone:
        (tmp_path / "g.game").write_text(meta, encoding="utf-8")
        media, path = tmp_path / "media", tmp_path / "g.game"
    else:
        (tmp_path / "g").mkdir()
        (tmp_path / "g" / "g.game").write_text(meta, encoding="utf-8")
        media, path = tmp_path / "g" / "media", tmp_path / "g" / "g.game"
    for name in files:
        media.mkdir(exist_ok=True)
        (media / name).write_bytes(b"IMG-" + name.encode())
    return tabula.Vault(tmp_path).load(path), media


@pytest.mark.parametrize("files, found", [
    (["cover.jpg"], "cover.jpg"),
    (["g_cover.png"], "g_cover.png"),
    (["G-Cover.WEBP"], "G-Cover.WEBP"),                  # case doesn't matter, "-" works like "_"
    (["cover.jpg", "g_cover.png"], "g_cover.png"),        # the game's own name wins
    (["cover.txt", "photo.jpg"], None),                    # only images called cover
    ([], None),
])
def test_found_by_name(tmp_path, files, found):
    game, media = make(tmp_path, files=files)
    assert game.cover == (media / found if found else None)


def test_frontmatter_overrides_and_empty_is_allowed(tmp_path):
    game, media = make(tmp_path, "cover: media/box.jpg\n", files=["cover.jpg", "box.jpg"])
    assert game.cover == media / "box.jpg"
    game, media = make(tmp_path / "b", "cover:\n", files=["cover.jpg"])
    assert game.cover == media / "cover.jpg"               # empty `cover:` -> found by name
    game, _ = make(tmp_path / "c", "cover: false\n", files=["cover.jpg"])
    assert game.cover is None                              # explicitly no cover


def test_standalone_games_need_their_slug(tmp_path):
    game, _ = make(tmp_path, files=["cover.jpg"], standalone=True)
    assert game.cover is None                              # the vault's media/ is shared by standalone games
    game, media = make(tmp_path / "b", files=["g_cover.jpg"], standalone=True)
    assert game.cover == media / "g_cover.jpg"


def test_check(tmp_path, capsys):
    make(tmp_path, "cover:\n", files=["cover.jpg"])
    assert tabula.main(["--vault", str(tmp_path), "check", "--no-color"]) == 0
    make(tmp_path / "b", "cover: media/missing.jpg\n")
    assert tabula.main(["--vault", str(tmp_path / "b"), "check", "--no-color"]) == 1
    assert "cover image not found: media/missing.jpg" in capsys.readouterr().out


def test_export_site_and_json_use_the_found_cover(tmp_path, capsys):
    make(tmp_path, files=["cover.png"])
    tabula.main(["--vault", str(tmp_path), "export", "g", "-o", "-"])
    html = capsys.readouterr().out
    assert '<img class="cover" src="data:image/png;base64,' in html
    tabula.main(["--vault", str(tmp_path), "show", "g", "--json"])
    assert json.loads(capsys.readouterr().out)["cover"].endswith("media/cover.png")
    tabula.main(["--vault", str(tmp_path), "site", "-o", str(tmp_path / "site")])
    capsys.readouterr()
    assert (tmp_path / "site" / "g" / "cover.png").read_bytes() == b"IMG-cover.png"
    assert 'src="g/cover.png"' in (tmp_path / "site" / "index.html").read_text(encoding="utf-8")
