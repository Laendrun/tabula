import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent

# Always test the tabula package from this repo (cli/tabula/), never another installed
# package with the same name (e.g. tabula-py, the PDF table extractor).
for candidate in (ROOT / "cli", ROOT):
    if (candidate / "tabula" / "__init__.py").exists():
        sys.path.insert(0, str(candidate))
        break
for name in [m for m in sys.modules if m == "tabula" or m.startswith("tabula.")]:
    sys.modules.pop(name)
import tabula  # noqa: E402

if not hasattr(tabula, "Vault"):
    raise ImportError(f"imported the wrong 'tabula' module: {tabula.__file__}")

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "vault"
EXAMPLES = next(p for p in (ROOT / "examples" / "vault", ROOT / "vault") if p.exists())


@pytest.fixture
def show(capsys):
    """Run `tabula show` on the test vault and return (exit code, stdout, stderr)."""
    def run(game, *args, vault=FIXTURES):
        code = tabula.main(["--vault", str(vault), "show", game, "--no-color", *args])
        out = capsys.readouterr()
        return code, out.out, out.err
    return run


@pytest.fixture
def check_body(tmp_path):
    """Write a one-game vault from a body (and optional frontmatter) and return check messages."""
    def run(body, meta="title: Test\nplayers: 2-4", files=None, require_defs=False, slug="g"):
        (tmp_path / slug).mkdir(exist_ok=True)
        (tmp_path / slug / f"{slug}.game").write_text(f"---\n{meta}\n---\n{body}", encoding="utf-8")
        for name, text in (files or {}).items():
            p = tmp_path / slug / name
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(text, encoding="utf-8")
        vault = tabula.Vault(tmp_path)
        game = vault.load(vault.find(slug))
        issues = tabula.check_game(game, vault, require_defs=require_defs)
        return [f"{i.level}: {i.msg}" for i in issues]
    return run