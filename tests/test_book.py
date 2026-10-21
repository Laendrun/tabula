"""`tabula book`: games as an EPUB book."""
import shutil
import subprocess
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path

import pytest

import tabula
from conftest import EXAMPLES, FIXTURES

XHTML = "{http://www.w3.org/1999/xhtml}"


def book(capsys, vault, *args):
    code = tabula.main(["--vault", str(vault), "book", *args])
    out = capsys.readouterr()
    return code, out.out, out.err


def read(path):
    with zipfile.ZipFile(path) as z:
        return {n: z.read(n) for n in z.namelist()}, z.infolist()


def text_of(xhtml: bytes) -> str:
    return " ".join("".join(ET.fromstring(xhtml).itertext()).split())


def test_whole_vault(tmp_path, capsys):
    code, out, _ = book(capsys, EXAMPLES, "-o", str(tmp_path))
    path = tmp_path / "family-game-vault.epub"
    assert code == 0 and f"wrote {path} (5 games)" in out
    files, infos = read(path)
    assert infos[0].filename == "mimetype" and infos[0].compress_type == zipfile.ZIP_STORED
    assert files["mimetype"] == b"application/epub+zip"
    opf = files["OEBPS/content.opf"].decode()
    assert "<dc:title>Family game vault</dc:title>" in opf and "<dc:language>fr</dc:language>" in opf
    assert 'property="dcterms:modified"' in opf
    spine = [i.split('"')[1] for i in opf.split("<spine")[1].split("<itemref ")[1:]]
    chapters = [f for f in files if f.startswith("OEBPS/") and f.endswith(".xhtml") and "nav" not in f and "title" not in f]
    assert len(spine) == 6 and len(chapters) == 5                       # title page + 5 games
    for name, data in files.items():                                    # every page is well-formed XHTML
        if name.endswith((".xhtml", ".opf", ".ncx", ".xml")):
            ET.fromstring(data)
    nav = text_of(files["OEBPS/nav.xhtml"])
    assert "Dame de pique" in nav and "Mise en place" in nav           # games and their sections
    assert any(n.startswith("OEBPS/images/") for n in files)            # the stone circle's picture is a file


def test_titles_are_in_alphabetical_order(tmp_path, capsys):
    book(capsys, EXAMPLES, "-o", str(tmp_path / "b.epub"))
    files, _ = read(tmp_path / "b.epub")
    title = text_of(files["OEBPS/title.xhtml"])
    names = ["Cercle de pierres", "Crazy Eights", "Dame de pique", "Oh My Socks!"]
    assert [title.index(n) for n in names] == sorted(title.index(n) for n in names)


def test_filters_and_badges(tmp_path, capsys):
    book(capsys, FIXTURES, "kitchen-sink", "-o", str(tmp_path / "all.epub"))
    page = text_of(read(tmp_path / "all.epub")[0]["OEBPS/kitchen-sink.xhtml"])
    assert "CHARLIE" in page and "KILO" in page and "+expo" in page     # everything, marked
    book(capsys, FIXTURES, "kitchen-sink", "-p", "3", "-o", str(tmp_path / "p3.epub"))
    page = text_of(read(tmp_path / "p3.epub")[0]["OEBPS/kitchen-sink.xhtml"])
    assert "KILO" not in page and "CHARLIE" in page                      # 3 players; extensions still there, marked
    book(capsys, FIXTURES, "kitchen-sink", "-e", "expo", "-o", str(tmp_path / "expo.epub"))
    page = text_of(read(tmp_path / "expo.epub")[0]["OEBPS/kitchen-sink.xhtml"])
    assert "CHARLIE" in page and "NOVEMBER" in page and "OSCAR" not in page


def test_default_names(tmp_path, capsys, monkeypatch):
    monkeypatch.chdir(tmp_path)
    book(capsys, FIXTURES, "kitchen-sink", "-p", "4", "-e", "expo", "--key")
    assert (tmp_path / "kitchen-sink-4p-expo-key.epub").exists()
    files, _ = read(tmp_path / "kitchen-sink-4p-expo-key.epub")
    assert "<dc:title>Kitchen Sink — key rules</dc:title>" in files["OEBPS/content.opf"].decode()
    assert "MIKE" in text_of(files["OEBPS/kitchen-sink.xhtml"])
    assert "DELTA" not in text_of(files["OEBPS/kitchen-sink.xhtml"])


def test_language(tmp_path, capsys):
    book(capsys, EXAMPLES, "-l", "en", "-o", str(tmp_path / "en.epub"))
    files, _ = read(tmp_path / "en.epub")
    assert "Hearts" in text_of(files["OEBPS/hearts.xhtml"])             # translated games in English
    assert 'xml:lang="en"' in files["OEBPS/hearts.xhtml"].decode()
    assert 'xml:lang="fr"' in files["OEBPS/oh-my-socks.xhtml"].decode()  # untranslated ones stay French


def test_images_links_and_awkward_text(tmp_path, capsys):
    v = tmp_path / "v"
    (v / "a" / "media").mkdir(parents=True)
    (v / "b").mkdir()
    shutil.copy(FIXTURES / "kitchen-sink" / "media" / "box.png", v / "a" / "media" / "cover.png")
    (v / "a" / "a.game").write_text(
        '---\ntitle: Àlpha & "Co"\nplayers: 2-4\n---\n# Règles\n\nVoir [B](game:b) et [le site](https://example.com).\n\n'
        "Une image distante ![Photo](https://example.com/p.jpg) au milieu.\n\n<b>pas du HTML</b> & co.\n", encoding="utf-8")
    (v / "b" / "b.game").write_text("---\ntitle: Bêta\nplayers: 3\n---\n# Règles\n\nTexte.\n", encoding="utf-8")
    book(capsys, v, "-o", str(tmp_path / "both.epub"))
    files, _ = read(tmp_path / "both.epub")
    a = files["OEBPS/a.xhtml"].decode()
    assert 'href="b.xhtml"' in a and 'href="https://example.com"' in a
    assert "example.com/p.jpg" not in a and "[Photo]" in a              # e-readers don't load web images
    assert "&lt;b&gt;pas du HTML&lt;/b&gt; &amp; co." in a               # written text stays text
    assert "OEBPS/images/cover.png" in files and 'src="images/cover.png"' in a
    code, _, err = book(capsys, v, "-p", "2", "-o", str(tmp_path / "two.epub"))
    a = read(tmp_path / "two.epub")[0]["OEBPS/a.xhtml"].decode()
    assert code == 0 and "left out: Bêta" in err
    assert 'href="b.xhtml"' not in a and "<span>B</span>" in a           # no link to a game that isn't in the book


def test_same_book_same_identifier(tmp_path, capsys):
    book(capsys, EXAMPLES, "-o", str(tmp_path / "1.epub"))
    book(capsys, EXAMPLES, "-o", str(tmp_path / "2.epub"))
    ident = [read(tmp_path / f)[0]["OEBPS/content.opf"].decode().split('id="bookid">')[1].split("<")[0]
             for f in ("1.epub", "2.epub")]
    assert ident[0] == ident[1] and ident[0].startswith("urn:uuid:")   # a rebuilt book replaces the old one


def test_errors(tmp_path, capsys):
    (tmp_path / "empty").mkdir()
    assert book(capsys, tmp_path / "empty")[0] == 1
    assert book(capsys, FIXTURES, "kitchen-sink", "-e", "nope", "-o", str(tmp_path / "x.epub"))[0] == 2


def epubcheck_jar():
    try:
        import epubcheck
    except ImportError:
        return None
    jar = Path(epubcheck.__file__).parent / "epubcheck.jar"
    return jar if jar.exists() and shutil.which("java") else None


@pytest.mark.parametrize("vault, args", [(EXAMPLES, []), (EXAMPLES, ["--key", "-l", "en"]),
                                         (FIXTURES, ["--all"]), (FIXTURES, ["-p", "2", "-e", "expo"])])
def test_epubcheck(tmp_path, capsys, vault, args):
    jar = epubcheck_jar()
    if not jar:
        pytest.skip("epubcheck (pip install epubcheck) and java are needed")
    book(capsys, vault, *args, "-o", str(tmp_path / "b.epub"))
    r = subprocess.run(["java", "-jar", str(jar), str(tmp_path / "b.epub")], capture_output=True, text=True)
    assert r.returncode == 0 and "No errors or warnings detected" in r.stdout, r.stdout + r.stderr
