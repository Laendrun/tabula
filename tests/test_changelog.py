"""The changelogs have an entry for the current versions (a reminder when bumping them)."""
import json
import re
from pathlib import Path

import tabula

ROOT = Path(__file__).resolve().parent.parent


def versions(path):
    return re.findall(r"^## (\d+\.\d+\.\d+)", path.read_text(encoding="utf-8"), re.M)


def test_cli_changelog_has_the_current_version():
    text = (ROOT / "cli" / "CHANGELOG.md").read_text(encoding="utf-8")
    assert "## Unreleased" in text
    assert versions(ROOT / "cli" / "CHANGELOG.md")[0] == tabula.__version__, \
        "add a section for the new version to cli/CHANGELOG.md"


def test_extension_changelog_has_the_current_version():
    pkg = json.loads((ROOT / "editors" / "vscode" / "package.json").read_text(encoding="utf-8"))
    assert versions(ROOT / "editors" / "vscode" / "CHANGELOG.md")[0] == pkg["version"], \
        "add a section for the new version to editors/vscode/CHANGELOG.md"
