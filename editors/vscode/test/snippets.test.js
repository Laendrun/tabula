// The snippets: valid, unique prefixes, and what they insert reads as tabula expects.
const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("fs");
const path = require("path");
const core = require("../src/core");

const snippets = JSON.parse(fs.readFileSync(path.join(__dirname, "..", "snippets", "tabula.json"), "utf8"));
const pkg = require("../package.json");

/** What a snippet inserts if you press Tab through it: placeholders' defaults, a choice's first option. */
function expand(body) {
  let text = body.join("\n").replace(/\$\{(\d+)\/\(\.\*\)\/\$\{1:\/capitalize\}\/\}/g, "\u0000CAP$1\u0000");
  const values = {};
  for (let i = 0; i < 10; i++) {               // nested placeholders: innermost first
    text = text.replace(/\$\{(\d+)\|([^|}]*?)(?:,[^|}]*)?\|\}/g, (_, n, first) => (values[n] = first));
    text = text.replace(/\$\{(\d+):([^${}]*)\}/g, (_, n, v) => (values[n] = v));
  }
  text = text.replace(/\u0000CAP(\d+)\u0000/g, (_, n) => values[n][0].toUpperCase() + values[n].slice(1));
  return text.replace(/\$\d+/g, "");
}

test("the snippets are declared for tabula files", () => {
  assert.deepEqual(pkg.contributes.snippets, [{ language: "tabula", path: "./snippets/tabula.json" }]);
});

test("every snippet has a unique prefix, a description and a body", () => {
  const prefixes = Object.values(snippets).map((s) => s.prefix);
  assert.equal(new Set(prefixes).size, prefixes.length);
  for (const [name, s] of Object.entries(snippets)) {
    assert.ok(s.description && Array.isArray(s.body) && s.body.length, name);
    assert.doesNotMatch(expand(s.body), /\$\{|\$\d/, name);            // every placeholder understood
  }
});

test("what they insert is valid tabula", () => {
  const by = Object.fromEntries(Object.values(snippets).map((s) => [s.prefix, expand(s.body)]));
  for (const p of ["game", "jeu"]) {
    const o = core.outline(by[p]);
    assert.deepEqual(o.headings.map((h) => h.attrs), ["#goal", "#components", "#setup", "#play", "#end", "#glossary"], p);
    assert.equal(o.components.length, 1, p);
    assert.equal(o.definitions[0].term, o.components[0].name[0].toUpperCase() + o.components[0].name.slice(1), p);
  }
  assert.equal(core.outline(by.card).definitions[0].term, "Name");
  assert.match(by.card, /^Name\n: points:: 1\n  effect:: What it does\.\n$/);
  const cat = core.outline(by.cards);
  assert.equal(cat.headings[0].attrs, "#cards");
  assert.equal(cat.definitions.length, 1);
  assert.equal(core.outline(by.comp).components[0].name, "name");
  assert.equal(core.outline(by.term).definitions[0].term, "Term");
  assert.equal(core.outline(by.keysec).headings[0].key, true);
  assert.equal(by.ptable.split("\n")[0], "| Setup | 2p | 3p | 4p |");
  assert.equal(by.choice, "{2p: this | *: otherwise}");
  assert.equal(by.cond, "{2p} ");
  assert.equal(by.inc.trim(), "![[deck-52#glossary]]");
  assert.match(by.sec, /^# Title \{#components\}/);
  assert.equal(by.callout, "> [!exemple] Title (optional)\n> Text.\n");
  assert.equal(by.players, "{player}");
  assert.match(by.sheet, /^---\ntitle: Feuille de score\nsize: a4\norientation: portrait\n---\n\n# Titre\n\n\| Joueur \| \{player\} \|/);
});
