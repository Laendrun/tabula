"""The JSON Schemas in spec/schemas: the same keys as tabula, and the example vault matches them."""
import json
from pathlib import Path

import pytest
import yaml

from tabula.fields import GAME_KEYS
from tabula.options import OPTION_KEYS
from tabula.sheet import SHEET_KEYS
from tabula.source import read_source
from tabula.wishlist import WISH_KEYS

ROOT = Path(__file__).resolve().parents[1]
SCHEMAS = ROOT / "spec" / "schemas"
EXAMPLES = ROOT / "examples" / "vault"


def schema(name):
    return json.loads((SCHEMAS / f"{name}.schema.json").read_text(encoding="utf-8"))


def test_same_keys_as_tabula():
    game = schema("game")
    assert tuple(game["properties"]) == GAME_KEYS
    option = next(o for o in game["properties"]["extensions"]["oneOf"][1]["additionalProperties"]["oneOf"]
                  if o.get("type") == "object")
    assert tuple(option["properties"]) == OPTION_KEYS
    assert set(schema("sheet")["properties"]) == set(SHEET_KEYS)
    wish = next(i for i in schema("wishlist")["items"]["oneOf"] if i.get("type") == "object")
    assert tuple(wish["properties"]) == WISH_KEYS


def frontmatter(path):
    meta, _ = read_source(path, None)
    return meta


def test_examples_match():
    jsonschema = pytest.importorskip("jsonschema")
    for name in ("game", "vault", "wishlist", "sheet"):
        jsonschema.Draft7Validator.check_schema(schema(name))
    v = jsonschema.Draft7Validator
    games = [p for p in EXAMPLES.rglob("*.game")]
    assert games
    for p in games:
        errors = [e.message for e in v(schema("game")).iter_errors(frontmatter(p))]
        assert not errors, (p, errors)
    for p in EXAMPLES.rglob("*.sheet"):
        assert not list(v(schema("sheet")).iter_errors(frontmatter(p))), p
    assert not list(v(schema("vault")).iter_errors(yaml.safe_load((EXAMPLES / "vault.yaml").read_text(encoding="utf-8"))))
    assert not list(v(schema("wishlist")).iter_errors(yaml.safe_load((EXAMPLES / "wishlist.yaml").read_text(encoding="utf-8"))))


def test_catches_mistakes():
    jsonschema = pytest.importorskip("jsonschema")
    v = jsonschema.Draft7Validator(schema("game"))
    assert not list(v.iter_errors({"title": "F", "players": "2-5", "series": "mine", "extensions": {
        "pandora": {"description": "P", "players": "2-10", "box": "blue"}, "bare": None}}))
    assert list(v.iter_errors({"title": "F", "players": "two"}))
    assert list(v.iter_errors({"title": "F", "players": 2, "extensions": {"p": {"year": "soon"}}}))
    assert list(jsonschema.Draft7Validator(schema("sheet")).iter_errors({"orientation": "sideways"}))
