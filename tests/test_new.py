"""`tabula new SLUG` (offline) and `tabula new bgg ID [SLUG]` (BoardGameGeek, faked here)."""
import pytest
import yaml

import tabula
import tabula.new as new

THING = b"""<?xml version="1.0" encoding="utf-8"?>
<items termsofuse="https://boardgamegeek.com/xmlapi/termsofuse">
  <item type="boardgame" id="13">
    <thumbnail>https://cf.geekdo-images.com/thumb/catan.jpg</thumbnail>
    <image>https://cf.geekdo-images.com/original/catan.png</image>
    <name type="primary" sortindex="1" value="CATAN" />
    <name type="alternate" sortindex="1" value="Die Siedler von Catan" />
    <name type="alternate" sortindex="1" value="Les Colons de Catane" />
    <description>Trade, build, settle.</description>
    <yearpublished value="1995" />
    <minplayers value="3" />
    <maxplayers value="4" />
    <playingtime value="120" />
    <minplaytime value="60" />
    <maxplaytime value="120" />
    <minage value="10" />
    <link type="boardgamecategory" id="1021" value="Economic" />
    <link type="boardgamecategory" id="1026" value="Negotiation" />
    <link type="boardgamemechanic" id="2072" value="Dice Rolling" />
    <link type="boardgamedesigner" id="11" value="Klaus Teuber" />
    <link type="boardgameartist" id="12" value="(Uncredited)" />
    <link type="boardgameartist" id="13" value="Michael Menzel" />
    <link type="boardgamepublisher" id="37" value="KOSMOS" />
    <link type="boardgamepublisher" id="38" value="Filosofia" />
  </item>
</items>"""

CARD = THING.replace(b'value="Economic"', b'value="Card Game"').replace(b'value="Negotiation"', b'value="Humor"')
SEARCH = b"""<items total="2">
  <item type="boardgame" id="9209"><name type="primary" value="Ticket to Ride" /><yearpublished value="2004" /></item>
  <item type="boardgame" id="14996"><name type="primary" value="Ticket to Ride: Europe" /><yearpublished value="2005" /></item>
</items>"""


@pytest.fixture
def vault(tmp_path):
    (tmp_path / "vault.yaml").write_text("name: V\nlanguage: fr\n", encoding="utf-8")
    return tmp_path


@pytest.fixture
def bgg(monkeypatch):
    """Fake BoardGameGeek: records every request, answers from `answers` (url part -> bytes or exception)."""
    calls, answers = [], {"/thing?id=13": THING, "/thing?id=99": CARD, "/search?": SEARCH, "catan.png": b"PNG"}

    def fetch(url, token=None):
        calls.append((url, token))
        for part, answer in answers.items():
            if part in url:
                if isinstance(answer, Exception):
                    raise answer
                return answer
        return b"<items></items>"
    monkeypatch.setattr(new, "fetch", fetch)
    monkeypatch.setenv("BGG_TOKEN", "secret-token")
    return calls, answers


def run(capsys, vault, *args):
    code = tabula.main(["--vault", str(vault), "new", *args])
    out = capsys.readouterr()
    return code, out.out, out.err


def meta_of(path):
    text = path.read_text(encoding="utf-8")
    return yaml.safe_load(text.split("---")[1]), text


# ------------------------------------------------------------------ offline

def test_blank_game_in_the_vault_language(vault, capsys):
    code, out, _ = run(capsys, vault, "skyjo")
    path = vault / "skyjo" / "skyjo.game"
    assert code == 0 and f"wrote {path}" in out and "fill in 'players:'" in out
    meta, text = meta_of(path)
    assert meta == {"title": "Skyjo", "players": None}
    assert "players:\n" in text                                     # left empty, not "null"
    for heading in ("# Matériel {#components}", "# Mise en place {#setup}", "# Glossaire {#glossary}"):
        assert heading in text
    assert text.count("<!-- TODO: à écrire -->") == 6
    tabula.main(["--vault", str(vault), "check", "skyjo", "--no-color"])
    out = capsys.readouterr().out
    assert "missing required 'players'" in out and "(6 TODO)" in out    # check is the reminder


def test_blank_game_with_options(vault, capsys):
    run(capsys, vault, "uno", "-t", "UNO", "-p", "2-10", "-l", "en")
    meta, text = meta_of(vault / "uno" / "uno.game")
    assert meta == {"title": "UNO", "players": "2-10", "language": "en"}
    assert "# Components {#components}" in text and "# End of the game {#end}" in text
    assert tabula.main(["--vault", str(vault), "check", "uno"]) == 0


def test_never_overwrites_without_force(vault, capsys):
    run(capsys, vault, "skyjo")
    (vault / "skyjo" / "skyjo.game").write_text("MY RULES", encoding="utf-8")
    with pytest.raises(SystemExit, match="already exists"):
        run(capsys, vault, "skyjo")
    assert (vault / "skyjo" / "skyjo.game").read_text() == "MY RULES"
    run(capsys, vault, "skyjo", "--force")
    assert "MY RULES" not in (vault / "skyjo" / "skyjo.game").read_text()
    (vault / "solo.game").write_text("STANDALONE", encoding="utf-8")       # a standalone game counts too
    with pytest.raises(SystemExit, match="already exists"):
        run(capsys, vault, "solo")


def test_bad_slug(vault, capsys):
    with pytest.raises(SystemExit, match="like 'les-colons'"):
        run(capsys, vault, "Les Colons")


def test_blank_game_never_goes_online(vault, capsys, monkeypatch):
    monkeypatch.setattr(new, "fetch", lambda *a, **k: pytest.fail("no network for 'tabula new SLUG'"))
    assert run(capsys, vault, "offline-game")[0] == 0


# ------------------------------------------------------------------ BoardGameGeek

def test_frontmatter_from_bgg(vault, capsys, bgg):
    calls, _ = bgg
    code, out, _ = run(capsys, vault, "bgg", "13")
    path = vault / "catan" / "catan.game"
    assert code == 0 and f"wrote {path}" in out
    meta, text = meta_of(path)
    assert meta == {
        "title": "CATAN", "players": "3-4", "duration": "60-120", "age": 10, "year": 1995, "type": ["board"],
        "tags": ["economic", "negotiation"], "designer": ["Klaus Teuber"], "artist": ["Michael Menzel"],
        "publisher": "KOSMOS", "links": {"bgg": "https://boardgamegeek.com/boardgame/13"}, "cover": "media/box.png",
    }
    assert (vault / "catan" / "media" / "box.png").read_bytes() == b"PNG"
    assert "# Matériel {#components}" in text                       # the skeleton, in the vault's language
    assert "other names on BoardGameGeek: Die Siedler von Catan, Les Colons de Catane" in out
    api = [c for c in calls if "xmlapi2" in c[0]]
    assert api and all(token == "secret-token" for _, token in api)
    assert [c for c in calls if "catan.png" in c[0]][0][1] is None    # the token only goes to the API
    assert tabula.main(["--vault", str(vault), "check", "catan"]) == 0


def test_bgg_with_slug_title_and_no_cover(vault, capsys, bgg):
    calls, _ = bgg
    run(capsys, vault, "bgg", "13", "colons", "-t", "Les Colons de Catane", "--no-cover")
    meta, _ = meta_of(vault / "colons" / "colons.game")
    assert meta["title"] == "Les Colons de Catane" and "cover" not in meta
    assert not any("catan.png" in url for url, _ in calls)


def test_card_games_are_typed_card(vault, capsys, bgg):
    run(capsys, vault, "bgg", "99", "cards")
    meta, _ = meta_of(vault / "cards" / "cards.game")
    assert meta["type"] == ["card"] and meta["tags"] == ["humor"]


def test_search_by_name_lists_ids(vault, capsys, bgg):
    code, out, _ = run(capsys, vault, "bgg", "ticket to ride")
    assert code == 0
    assert "9209  Ticket to Ride (2004)" in out and "14996  Ticket to Ride: Europe (2005)" in out
    assert not list(vault.glob("*/*.game"))                         # nothing written


def test_missing_token(vault, capsys, bgg, monkeypatch):
    monkeypatch.delenv("BGG_TOKEN")
    with pytest.raises(SystemExit, match="needs a token.*BGG_TOKEN.*tabula new SLUG"):
        run(capsys, vault, "bgg", "13")
    assert run(capsys, vault, "bgg", "13", "--token", "t")[0] == 0     # --token works too


def test_errors_are_explained(vault, capsys, bgg):
    _, answers = bgg
    answers["/thing?id=13"] = new.BggError("can't reach BoardGameGeek (offline); without internet, use 'tabula new SLUG'")
    code, _, err = run(capsys, vault, "bgg", "13")
    assert code == 1 and "without internet, use 'tabula new SLUG'" in err
    code, _, err = run(capsys, vault, "bgg", "12345")                  # unknown id: empty <items>
    assert code == 1 and "no game with id 12345" in err
    assert not list(vault.glob("*/*.game"))


def test_cover_failure_still_writes_the_game(vault, capsys, bgg):
    _, answers = bgg
    answers["catan.png"] = new.BggError("HTTP 404")
    code, _, err = run(capsys, vault, "bgg", "13")
    meta, _ = meta_of(vault / "catan" / "catan.game")
    assert code == 0 and "no cover image" in err and "cover" not in meta


def test_http_errors_become_messages(monkeypatch):
    import urllib.error

    def refuse(req, timeout):
        raise urllib.error.HTTPError(req.full_url, 401, "Unauthorized", {}, None)
    monkeypatch.setattr(new.urllib.request, "urlopen", refuse)
    with pytest.raises(new.BggError, match="token is missing, wrong or expired"):
        new.fetch("https://boardgamegeek.com/xmlapi2/thing?id=1", "bad")

    def offline(req, timeout):
        raise urllib.error.URLError("Name or service not known")
    monkeypatch.setattr(new.urllib.request, "urlopen", offline)
    with pytest.raises(new.BggError, match="can't reach BoardGameGeek"):
        new.fetch("https://boardgamegeek.com/xmlapi2/thing?id=1", "t")


def test_request_headers(monkeypatch):
    seen = {}

    class Response:
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def read(self): return b"ok"

    def capture(req, timeout):
        seen.update(req.headers)
        return Response()
    monkeypatch.setattr(new.urllib.request, "urlopen", capture)
    new.fetch("https://boardgamegeek.com/xmlapi2/thing?id=1", "abc")
    assert seen["Authorization"] == "Bearer abc" and seen["User-agent"].startswith("tabula/")


def test_slugify():
    assert new.slugify("Les Aventuriers du Rail : Europe") == "les-aventuriers-du-rail-europe"
    assert new.slugify("Château Combo") == "chateau-combo"
    assert new.slugify("7 Wonders Duel") == "7-wonders-duel"
