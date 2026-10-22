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

    def spelling(self, path, line, msg):
        """A word the dictionary doesn't know (check --spell): reported, but neither an error nor a warning."""
        self.append(Issue("spelling", Path(path), line, msg))


UNSAVED: dict[Path, str] = {}        # check --stdin: file contents from an editor, used instead of the disk


TODO_RE = re.compile(r"<!--\s*(?:TODO|FIXME)\b[\s:\-–—]*(.*?)\s*-->", re.S | re.I)


URL_SCHEME_RE = re.compile(r"^[A-Za-z][A-Za-z0-9+.-]*:")


def is_url(src: str) -> bool:
    """https://…, data:…: not a file of the vault (a Windows path like C:\\x counts too: never read)."""
    return bool(URL_SCHEME_RE.match(src or ""))


def local_file(base: Path, src: str, root: Path | None) -> Path | None:
    """A file a game names (a picture, its cover, a symbol), but only if it is inside the vault (`root`, else
    `base`): an absolute path, a web address or a ../ that leads out of the vault gives None. Exported pages and
    the site embed these files, so a game someone shares can't make them publish /etc/passwd or a key."""
    src = (src or "").strip()
    if not src or is_url(src) or src.startswith(("/", "\\", "~")) or Path(src).is_absolute():
        return None
    p = base / src
    try:
        if not p.resolve().is_relative_to((root or base).resolve()):
            return None
    except (OSError, ValueError):
        return None
    return p


def file_problem(base: Path, src: str, root: Path | None) -> str | None:
    """For check: 'not found' or 'outside the vault' for a file a game names (None when it's fine or a URL)."""
    if is_url(src.strip()) and not re.match(r"^[A-Za-z]:[\\/]", src.strip()):
        return None
    f = local_file(base, src, root)
    if f is None:
        return "outside the vault (only files inside the vault are used)"
    return None if f.exists() else "not found"


def raw_text(path: Path) -> str:
    """A file's text, or the unsaved text an editor sent with check --stdin."""
    text = UNSAVED.get(Path(path).resolve())
    if text is None:      # a file in another encoding is read anyway (check says so), never written back
        text = path.read_bytes().decode("utf-8", errors="replace")
    return text


def find_todos(path: Path) -> list[tuple[int, str]]:
    """The <!-- TODO: … --> (or FIXME) comments of a file: (line, text)."""
    text = raw_text(path).lstrip("\ufeff").replace("\r\n", "\n")
    return [(text.count("\n", 0, m.start()) + 1, " ".join(m.group(1).split()) or "TODO")
            for m in TODO_RE.finditer(text)]


FENCE_START_RE = re.compile(r"^\s*(```|~~~)")


def strip_comments(text: str) -> tuple[str, int | None, int | None]:
    """The text without its <!-- comments --> (their line breaks kept), except in code blocks and `code`.
    Also returns the line of a comment that is never closed and of a code block that is never closed."""
    out: list[str] = []
    fence, fence_line, in_comment, comment_line = None, 0, False, 0
    for k, line in enumerate(text.split("\n"), 1):
        if in_comment:
            j = line.find("-->")
            if j < 0:
                out.append("")
                continue
            line, in_comment = line[j + 3:], False
        elif fence:
            out.append(line)
            if line.strip().startswith(fence):
                fence = None
            continue
        elif m := FENCE_START_RE.match(line):
            fence, fence_line = m.group(1), k
            out.append(line)
            continue
        kept = []
        for part in re.split(r"(`[^`\n]*`)", line):          # `<!--` in inline code is text
            if in_comment:
                break
            if not part.startswith("`"):
                part = re.sub(r"<!--.*?-->", "", part)
                if (j := part.find("<!--")) >= 0:
                    part, in_comment, comment_line = part[:j], True, k
            kept.append(part)
        out.append("".join(kept))
    return "\n".join(out), (comment_line if in_comment else None), (fence_line if fence else None)


def read_source(path: Path, issues: Issues) -> tuple[dict, list[tuple[int, str]]]:
    text = raw_text(path)
    text = text.lstrip("\ufeff").replace("\r\n", "\n")
    if "\ufffd" in text and issues is not None and Path(path).resolve() not in UNSAVED:
        try:
            Path(path).read_bytes().decode("utf-8")
        except UnicodeDecodeError as e:
            issues.error(path, Path(path).read_bytes()[:e.start].count(10) + 1,
                         "the file isn't UTF-8 (Latin-1?): save it as UTF-8, or its accents show as �")
    if "\x00" in text:                 # tabula uses it as an internal marker: a stray one is dropped
        if issues is not None:
            issues.warn(path, text.count("\n", 0, text.index("\x00")) + 1,
                        "a NUL character (\\0) in the file: it is ignored")
        text = text.replace("\x00", "")
    text, open_comment, open_fence = strip_comments(text)
    if open_comment and issues is not None:
        issues.error(path, open_comment, "unclosed comment '<!--' (missing '-->'): the rest of the file is hidden")
    if open_fence and issues is not None:
        issues.warn(path, open_fence, "code block opened here is never closed: the rest of the file is shown as code")
    lines = text.split("\n")
    meta: dict = {}
    start = 0
    if lines and lines[0].strip() == "---":
        end = next((k for k in range(1, len(lines)) if lines[k].strip() in ("---", "...")), None)
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
