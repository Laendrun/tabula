"""Every example game renders with every common option combination."""
import pytest

import tabula
from conftest import EXAMPLES

GAMES = [p.stem for p in tabula.Vault(EXAMPLES).discover()]
OPTIONS = [[], ["--all"], ["-p", "2"], ["-p", "3"], ["-p", "4"], ["-p", "5"], ["--json"], ["-l", "fr"]]


@pytest.mark.parametrize("game", GAMES)
@pytest.mark.parametrize("opts", OPTIONS, ids=lambda o: " ".join(o) or "default")
def test_example_renders(show, game, opts):
    code, out, err = show(game, *opts, vault=EXAMPLES)
    if code == 2:                                   # player count outside the game's range is fine
        assert "players, not" in err
    else:
        assert code == 0 and out.strip()


def test_list(capsys):
    assert tabula.main(["--vault", str(EXAMPLES), "list"]) == 0
    out = capsys.readouterr().out
    assert all(g in out for g in GAMES)
    tabula.main(["--vault", str(EXAMPLES), "list", "-p", "5"])
    out = capsys.readouterr().out
    assert "hearts" in out and "stone-circle" not in out
