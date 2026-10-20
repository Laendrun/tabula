"""`tabula export`: a self-contained HTML page with the same filtering as `show`."""
import html.parser

import pytest

import tabula
from conftest import EXAMPLES, FIXTURES


class Nesting(html.parser.HTMLParser):
    VOID = {"meta", "link", "img", "br", "hr", "input"}

    def __init__(self):
        super().__init__()
        self.stack, self.errors, self.ids = [], [], []

    def handle_starttag(self, tag, attrs):
        self.ids += [v for k, v in attrs if k == "id"]
        if tag not in self.VOID:
            self.stack.append(tag)

    def handle_endtag(self, tag):
        if tag in self.VOID:
            return
        if self.stack and self.stack[-1] == tag:
            self.stack.pop()
        else:
            self.errors.append(tag)


@pytest.fixture
def export(capsys):
    def run(*args, vault=FIXTURES, game="kitchen-sink"):
        code = tabula.main(["--vault", str(vault), "export", game, "-o", "-", *args])
        return code, capsys.readouterr().out
    return run


def check_html(text):
    p = Nesting()
    p.feed(text)
    assert p.errors == [] and p.stack == [], (p.errors, p.stack)
    assert len(p.ids) == len(set(p.ids)), "duplicate ids"
    return p


def test_valid_and_self_contained(export):
    code, out = export("--all")
    assert code == 0 and out.startswith("<!doctype html>")
    check_html(out)
    assert "data:image/png;base64," in out                 # images are embedded
    assert "<style>" in out


def test_filters_match_show(export):
    _, out = export("-p", "2")
    assert "KILO" in out and "GOLF" in out and "HOTEL" not in out and "CHARLIE" not in out
    assert "Deal 9 cards" in out


def test_extension_is_highlighted(export):
    _, out = export("-e", "expo")
    assert 'class="badge ext">+expo' in out and "CHARLIE" in out
    assert 'class="card ext"' in out                        # Rocket/Comet cards get the extension corner


def test_glossary_cards_and_links(export):
    _, out = export("-e", "expo")
    p = check_html(out)
    assert "t-rocket" in p.ids and "t-card" in p.ids
    assert 'href="#t-rocket"' in out                        # [[rocket]] links to its card
    assert 'title="ZULU rocket text."' in out               # tooltip with the definition


def test_reference_to_hidden_term_is_not_a_link(export):
    _, out = export()                                       # base game: Comet card is hidden
    assert 'href="#t-comet"' not in out
    assert 'class="ref" title="only with +expo"' in out


def test_badges_for_undecided_conditions(export):
    _, out = export("--all")
    assert '<span class="badge open">2p</span>' in out      # player count: amber
    assert '<span class="badge opt">+expo</span>' in out    # extension: violet outline


def test_lists_and_renumbering(export):
    _, out = export("-p", "2")
    assert '<li value="3">' in out and "GOLF" in out
    assert 'value="5"' in out and "JULIET" in out


def test_toc_and_section_ids(export):
    _, out = export()
    p = check_html(out)
    assert {"components", "setup", "play", "glossary"} <= set(p.ids)
    assert '<nav class="toc"' in out and 'href="#glossary"' in out


def test_escaping(export):
    _, out = export()
    assert "{escaped}" in out and "[[literal]]" in out
    assert "<script" not in out


def test_language_and_ui_strings(export):
    _, out = export("-l", "fr")
    assert '<html lang="fr">' in out and "Sommaire" in out and "FR-ALPHA" in out


def test_writes_a_file_with_a_descriptive_name(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    assert tabula.main(["--vault", str(FIXTURES), "export", "kitchen-sink", "-p", "3", "-e", "expo"]) == 0
    assert (tmp_path / "kitchen-sink-3p-expo.html").exists()
    assert tabula.main(["--vault", str(FIXTURES), "export", "kitchen-sink", "-o", str(tmp_path / "x.html")]) == 0
    assert (tmp_path / "x.html").exists()


def test_section_export(export):
    _, out = export("-s", "glossary")
    assert "VICTOR" in out and "DELTA" not in out


@pytest.mark.parametrize("game", [p.stem for p in tabula.Vault(EXAMPLES).discover()])
def test_examples_export(export, game):
    code, out = export("--all", vault=EXAMPLES, game=game)
    assert code == 0
    check_html(out)


def test_extension_cards_keep_their_corner_with_all(export):
    _, out = export("--all")
    assert out.count('class="card ext"') == 2                   # Rocket and Comet
