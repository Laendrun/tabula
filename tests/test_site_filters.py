"""Game pages of `tabula site` let the reader choose players and extensions in the page."""
import json
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

import tabula
from conftest import FIXTURES

ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture(scope="module")
def page(tmp_path_factory):
    out = tmp_path_factory.mktemp("site") / "site"
    tabula.main(["--vault", str(FIXTURES), "site", "-o", str(out)])
    return out, (out / "kitchen-sink" / "index.html").read_text(encoding="utf-8")


def conds(html, pattern):
    """The data-c conditions of the elements whose HTML matches `pattern`."""
    out = []
    for m in re.finditer(r"<(\w+)([^>]*)>", html):
        if re.search(pattern, html[m.start():m.start() + 400]):
            c = re.search(r"data-c='([^']*)'", m.group(2))
            out.append(json.loads(c.group(1).replace("&quot;", '"')) if c else None)
    return out


def test_filter_bar(page):
    _, html = page
    bar = re.search(r'<form class="game-filters".*?</form>', html, re.S).group(0)
    assert [o for o in re.findall(r'<option value="(\d*)"', bar)] == ["", "2", "3", "4", "5"]
    assert 'id="f-all" checked' in bar
    assert 'value="quick"' in bar and 'value="expo"' in bar and 'title="The expansion"' in bar
    assert "<script>" in html and "tabula-filters" in html


def test_conditions_on_the_elements(page):
    _, html = page
    assert ["v", True, "quick"] in conds(html, r"^<li[^>]*>.{0,60}NOVEMBER")[0]
    assert conds(html, r"^<p[^>]*>.{0,60}SIERRA")[0] == [["p", False, [[3, 5]]]]
    assert conds(html, r'^<section[^>]*><h3 id="two-player-rule')[0] == [["p", False, [[2, 2]]]]
    assert conds(html, r'^<article[^>]*id="t-rocket"')[0] == [["v", False, "expo"]]
    # an inline choice keeps every branch, each with its condition
    choice = re.search(r"Deal <span class=\"choice\" data-choice>(.*?)</span></span>", html).group(1)
    assert choice.count('class="alt"') == 3 and "data-star" in choice
    # player tables: each column carries its player range, and conditional rows their condition
    assert conds(html, r"^<th[^>]*>3p</th>")[0] == [["p", False, [[3, 3]]]]
    assert conds(html, r"^<tr[^>]*><td[^>]*>.{0,120}Quick hand")[0] == [["v", False, "quick"]]


def test_card_counts_follow_the_selection(page):
    _, html = page
    m = re.search(r"data-counts='([^']*)'>4<", html)
    assert json.loads(m.group(1).replace("&quot;", '"')) == [[[["v", False, "expo"]], 4]]   # the parent's +expo


def test_static_export_has_no_filters(capsys):
    tabula.main(["--vault", str(FIXTURES), "export", "kitchen-sink", "-o", "-"])
    html = capsys.readouterr().out
    assert "data-c=" not in html and "tabula-filters" not in html and "<script>" not in html


def test_no_bar_when_there_is_nothing_to_choose(tmp_path, capsys):
    (tmp_path / "g").mkdir()
    (tmp_path / "g" / "g.game").write_text("---\ntitle: G\nplayers: 2\n---\n# Rules\n\nPlay.\n", encoding="utf-8")
    tabula.main(["--vault", str(tmp_path), "site", "-o", str(tmp_path / "site")])
    html = (tmp_path / "site" / "g" / "index.html").read_text(encoding="utf-8")
    assert '<form class="game-filters"' not in html and "<script>" not in html


# ------------------------------------------------------------------ in a real browser (skipped without playwright)

MARK = re.compile(r"(?<![A-Z])[A-Z]{4,}(?:-[A-Z]+)*(?![A-Za-z])")
HEADINGS = {"COMPONENTS", "SETUP", "PLAY", "GLOSSARY", "SHOWING"}


def shown_words(*args):
    out = subprocess.run([sys.executable, "-m", "tabula", "--vault", str(FIXTURES), "show", "kitchen-sink", "--no-color",
                          *args], capture_output=True, text=True, cwd=ROOT / "cli").stdout
    return set(MARK.findall(out.split("\n\n", 1)[1])) - HEADINGS


def test_page_shows_what_tabula_show_shows(page):
    sync_api = pytest.importorskip("playwright.sync_api")
    out, _ = page
    chromium = "/opt/pw-browsers/chromium"
    with sync_api.sync_playwright() as pw:
        try:
            browser = pw.chromium.launch(executable_path=chromium) if os.path.exists(chromium) else pw.chromium.launch()
        except Exception as e:                       # no browser installed
            pytest.skip(f"no browser: {e}")
        pg = browser.new_page()
        errors = []
        pg.on("pageerror", lambda e: errors.append(str(e)))
        url = f"file://{out}/kitchen-sink/index.html"
        for p in (None, 2, 3, 5):
            for options in (None, (), ("quick",), ("expo",), ("quick", "expo")):
                hash_ = "&".join(([f"p={p}"] if p else []) + ([f"o={','.join(options)}"] if options is not None else []))
                pg.goto(f"{url}#{hash_}" if hash_ else url)
                pg.reload()
                seen = set(MARK.findall(pg.inner_text("main"))) - HEADINGS
                args = (["-p", str(p)] if p else []) + (["--all"] if options is None else
                                                        [a for o in options for a in ("-v", o)])
                assert seen == shown_words(*args), f"p={p} options={options}"
        browser.close()
    assert not errors
