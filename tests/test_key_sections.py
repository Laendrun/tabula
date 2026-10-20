"""`## ! Title` key sections and `[[#Section]]` links."""
import json
import re

import tabula

BODY = """# Play {#play}

On your turn, add a block. If the tower falls, see [[#When the tower falls]].
Setup is in [[#setup|the first part]]. A broken link: [[#Nowhere]].

## ! When the tower falls {2-4p}

1. FALL-STOP the game.

### Exception {3+p}

FALL-EXCEPTION text.

---

FALL-STILL in the key section.

## Ending

ENDING text.

# Setup {#setup}

SETUP text.
"""


def game(tmp_path, body=BODY):
    (tmp_path / "g").mkdir(exist_ok=True)
    (tmp_path / "g" / "g.game").write_text(f"---\ntitle: G\nplayers: 2-5\n---\n{body}", encoding="utf-8")
    return tmp_path


def run(capsys, vault, cmd, *args):
    extra = ["--no-color"] if cmd in ("show", "lookup") else (["-o", "-"] if cmd == "export" else [])
    code = tabula.main(["--vault", str(vault), cmd, "g", *extra, *args])
    return code, capsys.readouterr().out


def test_key_heading_is_parsed():
    blocks = tabula.parse_blocks([(1, "## ! When it falls {2p}"), (2, "## !Also"), (3, "## Normal")])
    assert [(b.text, b.key) for b in blocks] == [("When it falls", True), ("Also", True), ("Normal", False)]
    assert blocks[0].cond.raw == "2p"


def test_show_marks_the_key_section_and_links(tmp_path, capsys):
    _, out = run(capsys, game(tmp_path), "show")
    assert "★ When the tower falls" in out
    assert "see → When the tower falls." in out
    assert "the first part (→ setup)" in out


def test_json(tmp_path, capsys):
    _, out = run(capsys, game(tmp_path), "show", "--json")
    data = json.loads(out)
    assert data["key_sections"] == ["When the tower falls"]
    assert "→" not in json.dumps(data["blocks"], ensure_ascii=False)          # plain text in JSON


def test_html_frames_the_whole_section(tmp_path, capsys):
    _, html = run(capsys, game(tmp_path), "export")
    sec = html[html.index('<section class="key-section">'):]
    sec = sec[:sec.index("</section>")]
    assert "FALL-STOP" in sec and "FALL-EXCEPTION" in sec and "FALL-STILL" in sec
    assert "ENDING" not in sec
    assert 'class="key"' in sec


def test_html_links_to_sections(tmp_path, capsys):
    _, html = run(capsys, game(tmp_path), "export")
    hid = re.search(r'<h3 id="([^"]+)" class="key">', html).group(1)
    assert f'<a class="ref section" href="#{hid}">When the tower falls</a>' in html
    assert '<a class="ref section" href="#setup">the first part</a>' in html
    assert '<span class="ref section">Nowhere</span>' in html


def test_link_to_a_filtered_section_is_not_a_link(tmp_path, capsys):
    _, html = run(capsys, game(tmp_path), "export", "-p", "5")            # the key section is 2-4p
    assert '<span class="ref section">When the tower falls</span>' in html


def test_section_links_match_like_references(tmp_path, capsys):
    body = "# Rules\n\nSee [[#événements]].\n\n# Événement\n\nX.\n"
    _, out = run(capsys, game(tmp_path, body), "check")
    assert "matches no section" not in out


def test_check_warns_about_broken_links_only(tmp_path, capsys):
    code, out = run(capsys, game(tmp_path), "check")
    assert code == 0 and out.count("matches no section") == 1 and "[[#Nowhere]]" in out
    assert "matches no component" not in out          # section links are not terms


def test_lookup_see_also_ignores_section_links(tmp_path, capsys):
    body = "# Glossary\n\nSetup\n: Read [[#setup]] first.\n\n# Setup {#setup}\n\nX.\n"
    _, out = run(capsys, game(tmp_path, body), "lookup", "setup")
    assert "see also" not in out
