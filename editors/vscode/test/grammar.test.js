"use strict";
// Tokenizes sample lines with VS Code's own TextMate engine and checks the scopes.
const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("fs");
const path = require("path");
const tm = require("vscode-textmate");
const oniguruma = require("vscode-oniguruma");

let grammar;
test.before(async () => {
  const wasm = fs.readFileSync(require.resolve("vscode-oniguruma/release/onig.wasm")).buffer;
  await oniguruma.loadWASM(wasm);
  const registry = new tm.Registry({
    onigLib: Promise.resolve({
      createOnigScanner: (p) => new oniguruma.OnigScanner(p),
      createOnigString: (s) => new oniguruma.OnigString(s),
    }),
    loadGrammar: async (scope) => {
      if (scope === "source.yaml") {      // VS Code ships the real one; a stub is enough here
        return tm.parseRawGrammar(JSON.stringify({ scopeName: "source.yaml", patterns: [{ match: "^\\w+(?=:)", name: "entity.name.tag.yaml" }] }), "yaml.json");
      }
      if (scope !== "source.tabula") return null;
      const file = path.join(__dirname, "..", "syntaxes", "tabula.tmLanguage.json");
      return tm.parseRawGrammar(fs.readFileSync(file, "utf8"), file);
    },
  });
  grammar = await registry.loadGrammar("source.tabula");
});

/** Tokenize a document; returns [line][{text, scopes}] */
function tokenize(text) {
  let state = tm.INITIAL;
  return text.split("\n").map((line) => {
    const r = grammar.tokenizeLine(line, state);
    state = r.ruleStack;
    return r.tokens.map((t) => ({ text: line.slice(t.startIndex, t.endIndex), scopes: t.scopes }));
  });
}

/** The scopes of the first token whose text is exactly `text` (or contains it). */
function scopesOf(lines, text) {
  const all = lines.flat();
  const tok = all.find((t) => t.text.trim() === text) || all.find((t) => t.text.includes(text));
  if (tok) return tok.scopes.join(" ");
  throw new Error(`no token '${text}'`);
}

const DOC = `---
title: Frantic
---
# Glossaire {#glossary}

## Cartes Puissance {+supercharge #cards}

- 60x cartes [[Gift]] — note
- ! Never [[lead|led]] hearts {3-4p}
1. Deal {2p: 7 | *: 5} cards.

Curse {+troublemaker}
: points:: 13
  Tu ne peux pas jouer **cette** carte, _jamais_.

---

! A key rule with [[Fuck You]].
> **Remarque**: a note.
| Joueurs | 3p | 4-5p |
|---------|----|------|
TANGO \\{escaped\\} and \`code {2p}\`.
<!-- hidden [[ref]] -->
\`\`\`
[[not a ref]] {2p}
\`\`\``;

test("frontmatter", () => {
  const l = tokenize(DOC);
  assert.match(l[0][0].scopes.join(" "), /punctuation.definition.frontmatter/);
  assert.match(scopesOf(l, "title"), /meta.embedded.block.frontmatter.* entity.name.tag.yaml/);
  assert.match(l[2][0].scopes.join(" "), /punctuation.definition.frontmatter/);
});

test("headings with roles and conditions", () => {
  const l = tokenize(DOC);
  assert.match(scopesOf(l, "Glossaire "), /markup.heading.tabula/);
  assert.match(scopesOf(l, "#glossary"), /entity.other.attribute-name.role/);
  assert.match(scopesOf(l, "+supercharge"), /keyword.control.option/);
  assert.match(scopesOf(l, "#cards"), /role/);
});

test("components, key items, choices", () => {
  const l = tokenize(DOC);
  assert.match(scopesOf(l, "60x"), /constant.numeric.quantity/);
  assert.match(scopesOf(l, "Gift"), /entity.name.tag.reference/);
  assert.match(l[8].find((t) => t.text === "!").scopes.join(" "), /keyword.other.key-rule/);
  assert.match(scopesOf(l, "led"), /string.other.reference.shown/);
  assert.match(scopesOf(l, "3-4p"), /constant.numeric.players/);
  assert.match(scopesOf(l, "2p"), /constant.numeric.players/);
  assert.match(scopesOf(l, "*"), /keyword.control.otherwise/);
});

test("definitions and fields", () => {
  const l = tokenize(DOC);
  assert.match(scopesOf(l, "+troublemaker"), /keyword.control.option/);
  assert.match(l[12][0].scopes.join(" "), /keyword.operator.definition/);
  assert.match(scopesOf(l, "points"), /variable.other.field/);
  assert.match(scopesOf(l, "::"), /punctuation.separator.field/);
  assert.match(scopesOf(l, "**cette**"), /markup.bold/);
  assert.match(scopesOf(l, "_jamais_"), /markup.italic/);
});

test("section end, key rule, note, table", () => {
  const l = tokenize(DOC);
  assert.match(l[15][0].scopes.join(" "), /keyword.control.section-end/);
  assert.match(scopesOf(l, "A key rule with "), /markup.bold.key-rule/);
  assert.match(scopesOf(l, "Fuck You"), /reference/);
  assert.match(scopesOf(l, ": a note."), /markup.quote/);
  assert.match(scopesOf(l, " 4-5p "), /constant.numeric.players/);
});

test("escapes, code, comments and fences are not tabula syntax", () => {
  const l = tokenize(DOC);
  assert.match(scopesOf(l, "\\{"), /constant.character.escape/);
  assert.doesNotMatch(scopesOf(l, "escaped"), /condition/);
  assert.match(scopesOf(l, "`code {2p}`"), /markup.inline.raw/);
  assert.match(scopesOf(l, " hidden [[ref]] "), /comment.block/);
  assert.match(scopesOf(l, "[[not a ref]] {2p}"), /markup.raw.block/);
});

test("--- later in the file is not frontmatter", () => {
  const l = tokenize("# A\n\ntext\n\n---\n\nmore");
  assert.match(l[4][0].scopes.join(" "), /section-end/);
  assert.doesNotMatch(scopesOf(l, "more"), /frontmatter/);
});

test("key sections and section links", () => {
  const l = tokenize("## ! When it falls {2p}\n\nSee [[#When it falls|this section]] or [[#setup]].");
  assert.match(l[0].find((t) => t.text === "!").scopes.join(" "), /keyword.other.key-rule/);
  assert.match(scopesOf(l, "When it falls "), /markup.heading/);
  assert.match(scopesOf(l, "#"), /punctuation.definition.section-link/);
  assert.match(scopesOf(l, "setup"), /entity.name.section.link/);
  assert.match(scopesOf(l, "this section"), /string.other.reference.shown/);
});

test("TODO stands out in comments", () => {
  const l = tokenize("<!-- TODO: write the cards -->");
  assert.match(scopesOf(l, "TODO"), /comment.block.*keyword.other.todo/);
  assert.match(scopesOf(l, ": write the cards "), /comment.block/);
});

test("shared fragment includes", () => {
  const l = tokenize("![[deck-52#Glossaire]]");
  assert.match(l[0][0].scopes.join(" "), /meta.include.*keyword.control.include/);
  assert.match(scopesOf(l, "deck-52"), /entity.name.namespace.fragment/);
  assert.match(scopesOf(l, "Glossaire"), /entity.name.section.link/);
});

test("values {=name}, in text and in table cells", () => {
  const l = tokenize("# T\n\nDeal {=hand} cards, {2p: 7 | *: 5}.\n\n| Cards | {=hand} |\n");
  const name = (line) => l[line].find((t) => t.text === "hand").scopes.join(" ");
  assert.match(name(2), /variable.other.value/);
  assert.match(name(4), /variable.other.value/);
  assert.doesNotMatch(name(2), /meta.condition/);
});

test("symbols :name:, not times or fields", () => {
  const l = tokenize("# T\n\nPay 3:gold: at 10:30: now.\n\nCard\n: cost:: 2 :gold:\n");
  assert.match(l[2].find((t) => t.text === "gold").scopes.join(" "), /constant.other.symbol/);
  assert.doesNotMatch(l[2].map((t) => t.scopes.join(" ")).filter((s, i) => l[2][i].text.includes("30")).join(" "), /symbol/);
  assert.match(l[5].find((t) => t.text === "gold").scopes.join(" "), /constant.other.symbol/);
});

test("callouts > [!type] Title", () => {
  const l = tokenize("# T\n\n> [!exemple] Un tour\n> Alice joue.\n> [not a callout]\n");
  assert.match(l[2].find((t) => t.text === "exemple").scopes.join(" "), /entity.name.type.callout/);
  assert.match(l[2].find((t) => t.text.includes("Un tour")).scopes.join(" "), /markup.heading.callout/);
  assert.doesNotMatch(l[4].map((t) => t.scopes.join(" ")).join(" "), /callout/);
});
