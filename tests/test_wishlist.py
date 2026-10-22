"""The wishlist: wishlist.yaml, tabula wish, check and the site page."""
import json

import pytest

import tabula

GAME = "---\ntitle: Frantic\nplayers: 2-8\n---\n# Rules\n\nPlay.\n"


def vault(tmp_path, wishes=None):
    (tmp_path / "frantic").mkdir(exist_ok=True)
    (tmp_path / "frantic" / "frantic.game").write_text(GAME, encoding="utf-8")
    (tmp_path / "vault.yaml").write_text("name: Jeux\nlanguage: fr\n", encoding="utf-8")
    if wishes is not None:
        (tmp_path / "wishlist.yaml").write_text(wishes, encoding="utf-8")
    return tmp_path


def run(capsys, v, *args):
    code = tabula.main(["--vault", str(v), *args])
    out = capsys.readouterr()
    return code, out.out, out.err


def test_add_list_remove(tmp_path, capsys):
    v = vault(tmp_path)
    assert "the wishlist is empty" in run(capsys, v, "wish")[1]
    run(capsys, v, "wish", "add", "Cascadia", "--priority", "2", "--price", "35 CHF", "--link", "https://x.ch/c")
    run(capsys, v, "wish", "add", "Pandora", "--for", "frant", "--priority", "1", "--note", "la boîte")
    run(capsys, v, "wish", "add", "Yes")
    text = (tmp_path / "wishlist.yaml").read_text(encoding="utf-8")
    assert "- name: Cascadia\n  priority: 2\n  price: 35 CHF\n  link: https://x.ch/c\n" in text
    assert "- name: Pandora\n  for: frantic\n  priority: 1\n  note: la boîte\n" in text
    assert '- name: "Yes"' in text                                   # YAML would read it as true: quoted
    code, out, _ = run(capsys, v, "wish", "--no-color")
    assert out.index("Cascadia") < out.index("Yes") < out.index("EXTENSIONS") < out.index("Pandora")
    assert "1 Pandora  for Frantic" in out and "2 Cascadia  35 CHF" in out
    _, out, _ = run(capsys, v, "wish", "--json", "--for", "frantic")
    assert json.loads(out) == [{"name": "Pandora", "for": "frantic", "priority": 1, "note": "la boîte"}]
    with pytest.raises(SystemExit, match="already on the wishlist"):
        run(capsys, v, "wish", "add", "cascadia")
    run(capsys, v, "wish", "remove", "cascadia")
    text = (tmp_path / "wishlist.yaml").read_text(encoding="utf-8")
    assert "Cascadia" not in text and "Pandora" in text and text.startswith("# Games and extensions")


def test_remove_keeps_comments(tmp_path, capsys):
    v = vault(tmp_path, "# ours\n- name: A   # first\n  priority: 1\n\n# the second one\n- name: B\n")
    run(capsys, v, "wish", "remove", "A")
    assert (tmp_path / "wishlist.yaml").read_text() == "# ours\n\n# the second one\n- name: B\n"


def test_check(tmp_path, capsys):
    v = vault(tmp_path, "- name: X\n  for: frantik\n  priority: high\n  pric: 3\n  link: www.x\n- for: frantic\n- Splendor\n")
    code, out, _ = run(capsys, v, "check", "--no-color")
    assert code == 1
    for msg in ("wishlist.yaml:1  unknown key 'pric' (did you mean 'price'?)",
                "'for: frantik' is not a game in the vault (did you mean 'frantic'?)",
                "priority must be a whole number", "link should be a web address", "wishlist.yaml:6  a wish needs a 'name'"):
        assert msg in out, msg
    assert "wishlist.yaml:7" not in out                                # "- Splendor": just a name is fine


def test_site(tmp_path, capsys):
    v = vault(tmp_path, "- name: Cascadia\n  priority: 1\n  link: https://x.ch\n- name: Pandora\n  for: frantic\n")
    run(capsys, v, "site", "-o", str(tmp_path / "site"))
    page = (tmp_path / "site" / "wishlist.html").read_text(encoding="utf-8")
    assert "<h1>Liste de souhaits</h1>" in page and '<span class="prio" title="priorité 1">1</span>' in page
    assert 'pour <a href="frantic/index.html">Frantic</a>' in page and 'id="for-frantic"' in page
    assert '♡ Souhaits (2)' in (tmp_path / "site" / "index.html").read_text(encoding="utf-8")
    assert 'href="../wishlist.html#for-frantic">♡ Souhaité (1)' in \
        (tmp_path / "site" / "frantic" / "index.html").read_text(encoding="utf-8")


def test_no_wishlist_no_page(tmp_path, capsys):
    v = vault(tmp_path)
    run(capsys, v, "site", "-o", str(tmp_path / "site"))
    assert not (tmp_path / "site" / "wishlist.html").exists()
    assert "Souhaits" not in (tmp_path / "site" / "index.html").read_text(encoding="utf-8")
