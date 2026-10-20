"""Small building blocks: ranges, conditions, roles, names, choices."""
import pytest

from tabula import (Ctx, cond_ok, norm, parse_attrs, parse_choice, parse_cond, parse_range, split_lang)


@pytest.mark.parametrize("spec, inside, outside", [
    ("4", [4], [3, 5]),
    ("2-4", [2, 3, 4], [1, 5]),
    ("5+", [5, 9], [4]),
    ("2,4", [2, 4], [3]),
    ("1-2,5+", [1, 2, 7], [3, 4]),
])
def test_ranges(spec, inside, outside):
    rng = parse_range(spec)
    assert all(any(lo <= n <= hi for lo, hi in rng) for n in inside)
    assert not any(any(lo <= n <= hi for lo, hi in rng) for n in outside)


@pytest.mark.parametrize("bad", ["", "x", "4-2", "2-", "-3", "2..4"])
def test_bad_ranges(bad):
    assert parse_range(bad) is None


@pytest.mark.parametrize("text", ["2p", "3-4p", "5+p", "3,5p", "!2p", "+expo", "-quick", "4p +teams", "*"])
def test_valid_conditions(text):
    assert parse_cond(text) is not None


@pytest.mark.parametrize("text", ["2", "p", "2 p", "p=2", "+", "#glossary", "2p glossary"])
def test_invalid_conditions(text):
    assert parse_cond(text) is None


def test_condition_evaluation():
    c = parse_cond("3-4p +expo")
    assert cond_ok(c, Ctx(players=3, variants={"expo"}))
    assert not cond_ok(c, Ctx(players=3))                       # extension off by default
    assert not cond_ok(c, Ctx(players=5, variants={"expo"}))
    assert cond_ok(c, Ctx(everything=True))                     # --all: every option, every count
    assert cond_ok(parse_cond("!2p"), Ctx(players=3))
    assert not cond_ok(parse_cond("!2p"), Ctx(players=2))
    assert cond_ok(parse_cond("-quick"), Ctx(players=2))
    assert not cond_ok(parse_cond("-quick"), Ctx(variants={"quick"}))


def test_attrs_roles_and_conditions():
    assert parse_attrs("#glossary") == (None, ["glossary"])
    cond, roles = parse_attrs("+expo #Cards")
    assert cond.raw == "+expo" and roles == ["cards"]
    assert parse_attrs("bad words") is None


def test_norm_ignores_case_and_plurals():
    assert norm("Cartes Chaussettes") == norm("carte chaussette")
    assert norm("jeux") == norm("jeu")
    assert norm("Boss") == "boss"


def test_split_lang():
    assert split_lang("hearts.fr") == ("hearts", "fr")
    assert split_lang("hearts.pt-BR") == ("hearts", "pt-BR")
    assert split_lang("hearts") == ("hearts", None)
    assert split_lang("v1.supercharge") == ("v1.supercharge", None)


def test_choice_parsing():
    branches = parse_choice("3p: 17 | 4p: 13 | *: 10")
    assert [c.raw for c, _ in branches] == ["3p", "4p", "*"]
    assert [t for _, t in branches] == ["17", "13", "10"]
    assert parse_choice("not a choice: really") is None
