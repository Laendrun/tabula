"""Card pictures: an image:: field, drawn on the card (site, export, book), not listed with the fields."""
import json
import zipfile

import tabula

PNG = bytes.fromhex("89504e470d0a1a0a0000000d4948445200000001000000010806000000"
                    "1f15c4890000000d49444154789c6360f8cf00000301010018dd8db40000000049454e44ae426082")
BODY = ("# Glossary\n\n## Cards {#cards}\n\nGift\n: points:: 7\n  image:: media/gift.png\n  Give two cards.\n\n"
        "Skip\n: points:: 5\n  Skip a turn.\n")


def vault(tmp_path, body=BODY):
    root = tmp_path / "v"
    (root / "g" / "media").mkdir(parents=True)
    (root / "g" / "media" / "gift.png").write_bytes(PNG)
    (root / "g" / "g.game").write_text(f"---\ntitle: G\nplayers: 2-4\n---\n{body}", encoding="utf-8")
    return root


def run(capsys, root, *args):
    code = tabula.main(["--vault", str(root), *args])
    return code, capsys.readouterr().out


def test_html(tmp_path, capsys):
    _, html = run(capsys, vault(tmp_path), "export", "g", "-o", "-")
    assert '<article class="card has-img" id="t-gift"><img class="card-img" src="data:image/png;base64,' in html
    assert '<img class="thumb" src="data:image/png;base64,' in html          # in the catalog table
    assert "<span>image</span>" not in html and "<th>image</th>" not in html


def test_terminal_cards_json(tmp_path, capsys):
    root = vault(tmp_path)
    _, out = run(capsys, root, "lookup", "g", "gift", "--no-color")
    assert "points: 7" in out and "[picture: media/gift.png]" in out and "image:" not in out
    _, out = run(capsys, root, "cards", "g", "--no-color")
    assert "image" not in out and "points" in out
    _, out = run(capsys, root, "show", "g", "--json")
    assert '"image": "media/gift.png"' in out


def test_book(tmp_path, capsys):
    root = vault(tmp_path)
    assert run(capsys, root, "book", "-o", str(tmp_path / "b.epub"))[0] == 0
    with zipfile.ZipFile(tmp_path / "b.epub") as z:
        assert sum(1 for n in z.namelist() if n.endswith(".png")) == 1
        chapter = next(z.read(n).decode() for n in z.namelist() if n.endswith(".xhtml") and b"Gift" in z.read(n))
        assert 'class="card-img"' in chapter and "data:" not in chapter


def test_check(tmp_path, capsys):
    body = BODY.replace("media/gift.png", "media/missing.png")
    code, out = run(capsys, vault(tmp_path, body), "check", "--no-color")
    assert code == 1 and "g.game:11  picture of 'Gift' not found: media/missing.png" in out


def test_a_card_without_picture_is_fine(tmp_path, capsys):
    body = BODY + "\nThird\n: points:: 1\n  image:: media/gift.png\n  X.\n"      # 2 of 3 cards have one: no warning
    code, out = run(capsys, vault(tmp_path, body), "check", "--no-color")
    assert code == 0 and "image" not in out
