"use strict";
// The outline of a text, from the real `tabula outline --json` of this repository (the parser the extension reads).
const cp = require("child_process");
const fs = require("fs");
const os = require("os");
const path = require("path");

const PYTHON = process.env.PYTHON || (process.platform === "win32" ? "python" : "python3");
const CLI = path.join(__dirname, "..", "..", "..", "cli");

/** { o, root, lines }: the outline of `text` as the file `file` of a new vault with `files` in it. */
function outlineOf(text, { file = "g/g.game", files = {} } = {}) {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), "tabula-outline-"));
  if (!("vault.yaml" in files)) fs.writeFileSync(path.join(root, "vault.yaml"), "name: T\n");
  for (const [name, content] of Object.entries({ ...files, [file]: text })) {
    fs.mkdirSync(path.dirname(path.join(root, name)), { recursive: true });
    fs.writeFileSync(path.join(root, name), content);
  }
  const out = cp.execFileSync(PYTHON, ["-m", "tabula", "--vault", root, "outline", path.join(root, file), "--json", "--stdin"],
    { input: text, env: { ...process.env, PYTHONPATH: CLI } });
  return { o: JSON.parse(out.toString("utf8")), root, lines: text.split("\n") };
}

module.exports = { outlineOf };
