"""Symbols: :name: defined in vault.yaml or the frontmatter, drawn as text or as small images."""
import zipfile

import tabula
from tabula.symbols import SYMBOL_RE

PNG = bytes.fromhex("89504e470d0a1a0a0000000d4948445200000001000000010806000000"
                    "1f15c4890000000d49444154789c6360f8cf00000301010018dd8db40000000049454e44ae426082")


def vault(tmp_path, body, meta="", config="language: en\nsymbols:\n  gold: media/gold.png\n  star: ⭐\n"):
    root = tmp_path / "v"
    (root / "g" / "media").mkdir(parents=True, exist_ok=True)
    (root / "media").mkdir(exist_ok=True)
    (root / "media" / "gold.png").write_bytes(PNG)
    (root / "g" / "media" / "key.png").write_bytes(PNG)
    (root / "vault.yaml").write_text(config, encoding="utf-8")
    (root / "g" / "g.game").write_text(f"---\ntitle: G\nplayers: 2-4\n{meta}---\n{body}", encoding="utf-8")
    return root


KEY = 'symbols:\n  key: {image: media/key.png, text: "🔑"}\n  star: ★\n'
BODY = ("# Rules\n\nPay 3 :gold: and 1 :key: for 2 :star:. At 10:30: fine, `:gold:` in code, :other: stays.\n\n"
        ":star:\n\n| Cost | :gold: |\n|---|---|\n| 1 | 2 :key: |\n\n# Glossary\n\nCard\n: cost:: 2 :gold:\n")


def test_pattern():
    assert [m.group(1) for m in SYMBOL_RE.finditer(":a: x:b: :c:d 10:30: :e:: http://x:y: (:f:)")] == ["a", "f"]


def test_terminal(tmp_path, capsys):
    tabula.main(["--vault", str(vault(tmp_path, BODY, KEY)), "show", "g", "--no-color"])
    out = capsys.readouterr().out
    assert "Pay 3 gold and 1 🔑 for 2 ★. At 10:30: fine, `:gold:` in code, :other: stays." in out   # the game's ★ wins
    assert "\n★\n" in out                                   # alone on its line: text, not a figure
    assert "Cost  gold" in out and "1     2 🔑" in out
    assert "cost: 2 gold" in out


def test_html(tmp_path, capsys):
    tabula.main(["--vault", str(vault(tmp_path, BODY, KEY)), "export", "g", "-o", "-"])
    html = capsys.readouterr().out
    assert html.count('<img class="sym" src="data:image/png;base64,') == 5        # gold ×3, key ×2
    assert 'alt="🔑"' in html and "<code>:gold:</code>" in html and "img.sym{" in html
    assert "<figure" not in html


def test_book_packs_the_images(tmp_path, capsys):
    root = vault(tmp_path, BODY, KEY)
    assert tabula.main(["--vault", str(root), "book", "-o", str(tmp_path / "b.epub")]) == 0
    with zipfile.ZipFile(tmp_path / "b.epub") as z:
        chapter = next(z.read(n).decode() for n in z.namelist() if n.endswith(".xhtml") and "g" in n and "nav" not in n
                       and "Pay 3" in z.read(n).decode())
        assert chapter.count('class="sym"') == 5 and "data:" not in chapter
        assert sum(1 for n in z.namelist() if n.endswith(".png")) == 2


def test_check(tmp_path, capsys):
    meta = "symbols:\n  bad name: x\n  pic: media/missing.png\n  odd: {image: media/key.png, colour: red}\n"
    root = vault(tmp_path, "# Rules\n\nPay :golld: and :hello:.\n", meta,
                 config="language: en\nsymbols:\n  gold: media/gold.png\n  ghost: media/none.png\n")
    code = tabula.main(["--vault", str(root), "check", "--no-color"])
    out = capsys.readouterr().out
    assert code == 1
    assert "vault.yaml:1  symbol 'ghost': image not found: media/none.png" in out
    assert "symbol name 'bad name'" in out and "symbol 'pic': image not found" in out
    assert "symbol 'odd': only 'image' and 'text'" in out
    assert "':golld:' is not a symbol: did you mean ':gold:'?" in out
    assert "hello" not in out                       # an unknown :word: far from any symbol is just text


def test_spelling_skips_symbols(tmp_path, capsys, monkeypatch):
    from tabula import spell
    monkeypatch.setattr(spell, "check_spelling", spell.check_spelling)
    assert spell.prose("Pay :gld: now").split() == ["Pay", "now"]
