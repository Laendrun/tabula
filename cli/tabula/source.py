"""Reading .game files (frontmatter, comments) and collecting issues."""
from __future__ import annotations

import sys
import re
from dataclasses import dataclass
from pathlib import Path

try:
    import yaml
except ImportError:  # pragma: no cover
    sys.exit("tabula needs PyYAML:  pip install pyyaml")

@dataclass
class Issue:
    level: str
    path: Path
    line: int
    msg: str


class Issues(list):
    def error(self, path, line, msg):
        self.append(Issue("error", Path(path), line, msg))

    def warn(self, path, line, msg):
        self.append(Issue("warning", Path(path), line, msg))

    def todo(self, path, line, msg):
        """A reminder left in the file (<!-- TODO: … -->): reported, but neither an error nor a warning."""
        self.append(Issue("todo", Path(path), line, msg))


UNSAVED: dict[Path, str] = {}        # check --stdin: file contents from an editor, used instead of the disk


TODO_RE = re.compile(r"<!--\s*(?:TODO|FIXME)\b[\s:\-–—]*(.*?)\s*-->", re.S | re.I)


def raw_text(path: Path) -> str:
    """A file's text, or the unsaved text an editor sent with check --stdin."""
    text = UNSAVED.get(Path(path).resolve())
    return path.read_text(encoding="utf-8") if text is None else text


def find_todos(path: Path) -> list[tuple[int, str]]:
    """The <!-- TODO: … --> (or FIXME) comments of a file: (line, text)."""
    text = raw_text(path).lstrip("\ufeff").replace("\r\n", "\n")
    return [(text.count("\n", 0, m.start()) + 1, " ".join(m.group(1).split()) or "TODO")
            for m in TODO_RE.finditer(text)]


def read_source(path: Path, issues: Issues) -> tuple[dict, list[tuple[int, str]]]:
    text = raw_text(path)
    text = text.lstrip("\ufeff").replace("\r\n", "\n")
    text = re.sub(r"<!--.*?-->", lambda m: "\n" * m.group(0).count("\n"), text, flags=re.S)
    if (i := text.find("<!--")) >= 0:
        issues.error(path, text.count("\n", 0, i) + 1, "unclosed comment '<!--' (missing '-->')")
        text = text[:i]
    lines = text.split("\n")
    meta: dict = {}
    start = 0
    if lines and lines[0].strip() == "---":
        end = next((k for k in range(1, len(lines)) if lines[k].strip() == "---"), None)
        if end is None:
            issues.error(path, 1, "frontmatter starts with '---' but is never closed")
        else:
            try:
                meta = yaml.safe_load("\n".join(lines[1:end])) or {}
                if not isinstance(meta, dict):
                    issues.error(path, 2, "frontmatter must be YAML 'key: value' lines")
                    meta = {}
            except yaml.YAMLError as e:
                mark = getattr(e, "problem_mark", None)
                issues.error(path, (mark.line + 2) if mark else 1,
                             f"invalid YAML in frontmatter: {getattr(e, 'problem', e)}")
            start = end + 1
    return meta, [(k + 1, lines[k].rstrip()) for k in range(start, len(lines))]
