"use strict";
const test = require("node:test");
const assert = require("node:assert/strict");
const core = require("../src/core");

test("check arguments", () => {
  assert.deepEqual(core.checkArgs({ file: "a.game", stdin: true }), ["check", "a.game", "--json", "--stdin"]);
  assert.deepEqual(core.checkArgs({ file: "a.game", spell: true }), ["check", "a.game", "--json", "--spell"]);
  assert.deepEqual(core.fmtArgs({ file: "a.game", vault: "V" }), ["--vault", "V", "fmt", "a.game", "--stdin"]);
  assert.deepEqual(core.fmtArgs({ extraArgs: ["t.py"] }), ["t.py", "fmt"]);
  assert.deepEqual(core.previewArgs({ file: "a.sheet" }), ["sheet", "a.sheet", "--stdin", "-o", "-"]);
  assert.deepEqual(core.previewArgs({ file: "a.game", vault: "V" }), ["--vault", "V", "export", "a.game", "--interactive", "--lines", "--stdin", "-o", "-"]);
  assert.deepEqual(
    core.checkArgs({ vault: "V", extraArgs: ["cli/tabula.py"], definitions: true }),
    ["cli/tabula.py", "--vault", "V", "check", "--json", "--definitions"]
  );
});

test("settings expansion", () => {
  assert.equal(core.expand("${workspaceFolder}/cli/tabula.py", "/w", "/h"), "/w/cli/tabula.py");
  assert.equal(core.expand("~/vault", "/w", "/h"), "/h/vault");
  assert.equal(core.expand("tabula", "/w", "/h"), "tabula");
});

test("parse check output", () => {
  const r = core.parseCheckOutput('{"vault": "/v", "files": ["/v/g/g.game"], "issues": []}');
  assert.deepEqual(r, { vault: "/v", files: ["/v/g/g.game"], issues: [] });
  assert.throws(() => core.parseCheckOutput("usage: tabula ..."), /no JSON/);
});

test("squiggle goes on what the message quotes", () => {
  const msg = "[[nope]] matches no component ('- 1x [[nope]]' in a list) and no definition ('nope' then ': …')";
  assert.deepEqual(core.issueColumns("See the [[nope]] card.", msg), [8, 16]);
  assert.deepEqual(core.issueColumns("## Setup {2x}", "invalid heading attributes '{2x}' (roles look like #glossary)"), [9, 13]);
  assert.deepEqual(core.issueColumns("  some text  ", "something without quotes"), [2, 11]);
  assert.deepEqual(core.issueColumns("", "empty line"), [0, 0]);
  // a word: the whole word, not the same letters inside a longer one
  assert.deepEqual(core.issueColumns("Les cartes, la carte.", "unknown word 'carte'"), [15, 20]);
  assert.deepEqual(core.issueColumns("coup d'oeil", "unknown word 'd'oeil'"), [5, 11]);
});

test("fold is case, accent and plural insensitive", () => {
  assert.equal(core.fold("Événements"), core.fold("evenement"));
  assert.equal(core.fold("Cartes Puissance"), core.fold("carte puissance"));
  assert.notEqual(core.fold("Pass"), core.fold("Pa"));
});

const GAME = `---
title: G
players: 2-4
---
# Components {#components}

- 60x [[card]] — ALPHA
- {+expo} 10x cartes [[Gift]]

\`\`\`
# not a heading
Fake
: not a definition
\`\`\`

<!--
# hidden heading
-->

# Glossary {#glossary}

## Cards {#cards}

{+expo} Gift
: points:: 2
  Give two cards.

Card
: The basic piece.

---

Effect {+expo}
: An effect.

## Two players {2p}

## Extra

Text.

---

---

After.
`;

test("outline: headings, definitions, components", () => {
  const o = core.outline(GAME);
  assert.deepEqual(o.headings.map((h) => [h.title, h.level, h.attrs]), [
    ["Components", 1, "#components"], ["Glossary", 1, "#glossary"], ["Cards", 2, "#cards"],
    ["Two players", 2, "2p"], ["Extra", 2, ""],
  ]);
  assert.deepEqual(o.definitions.map((d) => [d.term, d.cond]), [["Gift", "+expo"], ["Card", ""], ["Effect", "+expo"]]);
  assert.deepEqual(o.components.map((c) => [c.name, c.quantity]), [["card", "60"], ["Gift", "10"]]);
  const lines = GAME.split("\n");
  const gift = o.definitions[0];
  assert.equal(lines[gift.end], "  Give two cards.");
});

test("outline: '---' ends sections", () => {
  const o = core.outline(GAME);
  const lines = GAME.split("\n");
  const byTitle = Object.fromEntries(o.headings.map((h) => [h.title, h]));
  assert.equal(lines[byTitle.Cards.end], "---");                        // closed by the first ---
  assert.equal(lines[byTitle.Extra.end], "---");                        // "Two players" was empty
  assert.equal(byTitle.Glossary.end, byTitle.Extra.end + 2);            // the second --- after Extra closes Glossary
  assert.equal(lines[byTitle["Two players"].line + 1], "");
  assert.equal(byTitle["Two players"].end, byTitle["Two players"].line);
});

test("reference under the cursor and its targets", () => {
  const line = "Shuffle the [[cards|deck]] and the [[Gift]].";
  assert.equal(core.refAt(line, 15).name, "cards");
  assert.equal(core.refAt(line, 38).name, "Gift");
  assert.equal(core.refAt(line, 3), null);
  const lines = GAME.split("\n");
  assert.deepEqual(core.findTargets(GAME, "cards").map((l) => lines[l]), ["Card"]);       // the definition wins
  assert.deepEqual(core.findTargets(GAME, "gifts").map((l) => lines[l]), ["{+expo} Gift"]);
  assert.deepEqual(core.findTargets(GAME, "nothing"), []);
});

test("key sections and section links", () => {
  const text = "# Play {#play}\n\nSee [[#When it falls|this]] and [[#setup]].\n\n## ! When it falls {2p}\n\nStop.\n\n# Mise en place {#setup}\n\nX.\n";
  const lines = text.split("\n");
  const o = core.outline(text);
  assert.deepEqual(o.headings.map((h) => [h.title, h.key]), [["Play", false], ["When it falls", true], ["Mise en place", false]]);
  assert.equal(core.refAt(lines[2], 8).name, "#When it falls");
  assert.deepEqual(core.findTargets(text, "#when it FALL").map((l) => lines[l]), ["## ! When it falls {2p}"]);
  assert.deepEqual(core.findTargets(text, "#setup").map((l) => lines[l]), ["# Mise en place {#setup}"]);
  assert.deepEqual(core.findTargets(text, "#nowhere"), []);
});

const SAMPLE = `---
title: G
---
# Matériel {#components}

- 60x [[carte]]
- 2x [[Pion]] — rouges

## ! Si la tour tombe {2p}

Arrête la partie, voir [[Carte]].

# Glossaire {#glossary}

Carte {+expo}
: points:: 3
  timing:: 1st
  Une [[carte|carte]] simple.

Carte
: Doublon ignoré.

### Déplacer le [[Pion]]

Texte.
`;

test("completion context", () => {
  assert.deepEqual(core.completionContext("Voir [[ca", 9), { section: false, typed: "ca", start: 7, closed: false });
  assert.deepEqual(core.completionContext("Voir [[#Si]] x", 10), { section: true, typed: "Si", start: 8, closed: true });
  assert.equal(core.completionContext("Voir [[carte]] ok", 16), null);          // after a finished reference
  assert.equal(core.completionContext("no ref", 3), null);
  assert.deepEqual(core.completionContext("[[]]", 2), { section: false, typed: "", start: 2, closed: true });
});

test("completions: terms, then components, then sections and roles", () => {
  const { terms, sections } = core.completions(SAMPLE);
  assert.deepEqual(terms.map((t) => [t.label, t.kind, t.detail]), [
    ["Carte", "definition", "{+expo}"],        // the duplicate definition is listed once
    ["Pion", "component", "2x"],               // "carte" already has a definition
  ]);
  assert.equal(terms[0].doc, "**points:** 3  \n**timing:** 1st\n\nUne carte simple.");
  assert.deepEqual(sections.map((s) => [s.label, s.kind]), [
    ["Matériel", "section"], ["components", "role"], ["Si la tour tombe", "section"],
    ["Glossaire", "section"], ["glossary", "role"], ["Déplacer le Pion", "section"],
  ]);
  assert.equal(sections[2].detail, "★ ##");
});

test("hover: definitions, components and sections", () => {
  const card = core.hoverText(SAMPLE, "cartes");
  assert.match(card, /^\*\*Carte\*\* `\{\+expo\}`\n\n\*\*points:\*\* 3/);
  assert.match(card, /Doublon ignoré/);                   // both definitions are shown
  assert.match(card, /- 60x carte/);                      // and the component line
  assert.equal(core.hoverText(SAMPLE, "pion"), "- 2x Pion — rouges");
  assert.match(core.hoverText(SAMPLE, "#si la tour tombe"), /^\*\*★ Si la tour tombe\*\* `\{2p\}`\n\nArrête la partie, voir Carte\./);
  assert.match(core.hoverText(SAMPLE, "#glossary"), /^\*\*Glossaire\*\*/);
  assert.match(core.hoverText(SAMPLE, "#déplacer le pion"), /^\*\*Déplacer le Pion\*\*\n\nTexte\./);
  assert.equal(core.hoverText(SAMPLE, "nothing"), null);
  assert.equal(core.hoverText(SAMPLE, "#nothing"), null);
});

test("TODO reminders are information, not warnings", () => {
  const S = { Error: 0, Warning: 1, Information: 2 };
  assert.equal(core.severity("error", S), 0);
  assert.equal(core.severity("warning", S), 1);
  assert.equal(core.severity("todo", S), 2);
  assert.equal(core.severity("spelling", S), 2);
});

test("include lines: under the cursor, while typing, hover", () => {
  assert.deepEqual(core.includeAt("![[deck-52#Glossaire]]", 5), { name: "deck-52", section: "Glossaire", start: 0, end: 22 });
  assert.deepEqual(core.includeAt("  ![[deck-52]]", 4), { name: "deck-52", section: null, start: 2, end: 14 });
  assert.equal(core.includeAt("See ![[deck-52]] here", 8), null);           // not alone on its line
  assert.deepEqual(core.includeContext("![[de", 5), { name: "de", section: null, start: 3, closed: false });
  assert.deepEqual(core.includeContext("![[deck-52#Glo]]", 14), { name: "deck-52", section: "Glo", start: 11, closed: true });
  assert.equal(core.includeContext("[[de", 4), null);
  const frag = "# Components {#components}\n\n- 52x [[card]]\n\n# Glossary\n\nCard\n: One card.\n";
  assert.match(core.includeHover(frag, "deck-52", "components"), /^\*from `_shared\/deck-52`\*\n\n\*\*Components\*\*/);
  assert.equal(core.includeHover(frag, "deck-52", null), "**Fragment `deck-52`**\n\n- Components\n- Glossary");
  assert.equal(core.includeHover(frag, "deck-52", "nothing"), null);
});

test("a field can continue on indented lines", () => {
  const text = "# Cards {#cards}\n\n8\n: effet:: Vous ne pouvez pas\n    vous défausser d'un 8.\n    Terminez la manche.\n  valeur:: 8\n  Texte.\n";
  assert.equal(core.hoverText(text, "8"),
    "**8**\n\n**effet:** Vous ne pouvez pas vous défausser d'un 8. Terminez la manche.  \n**valeur:** 8\n\nTexte.");
});

test("values: YAML entries, the vault's and the game's, typing and hovering", () => {
  const vault = 'language: fr\nvalues:\n  target: 100\n  hand: {2p: 9, "*": 5}\nsymbols:\n  or: 🪙\n';
  const game = '---\ntitle: G\nvalues:\n  hand:\n    2p: 7\n    "*": 5\n  "max": 3   # comment\nplayers: 2-4\n---\n# Rules\nvalues:\n  not: frontmatter\n';
  assert.deepEqual(core.yamlEntries(game, "values").map((e) => [e.name, e.value]), [["hand", "2p: 7, *: 5"], ["max", "3"]]);
  const v = core.valuesOf(game, vault);
  assert.deepEqual(v.map((x) => [x.name, x.from]), [["target", "vault.yaml"], ["hand", "this game"], ["max", "this game"]]);
  assert.deepEqual(core.yamlEntries(vault, "symbols"), [{ name: "or", value: "🪙", line: 5 }]);
  assert.deepEqual(core.valueContext("Deal {=ha", 9), { typed: "ha", start: 7, closed: false });
  assert.equal(core.valueContext("Deal {=ha}", 9).closed, true);
  assert.equal(core.valueContext("Deal {2p: x", 11), null);
  assert.deepEqual(core.valueAt("Deal {=hand} cards", 8), { name: "hand", start: 5, end: 12 });
  assert.equal(core.valueAt("Deal {=hand} cards", 15), null);
});

test("symbols: definitions, typing and hovering", () => {
  const vault = 'symbols:\n  gold: media/gold.png\n  star: "⭐"\n';
  const game = '---\nsymbols:\n  key: {image: media/key.png, text: "🔑"}\n  star: ★\n---\n';
  assert.deepEqual(core.symbolsOf(game, vault), [
    { name: "gold", image: "media/gold.png", text: null, from: "vault.yaml" },
    { name: "star", image: null, text: "★", from: "this game" },
    { name: "key", image: "media/key.png", text: "🔑", from: "this game" },
  ]);
  assert.deepEqual(core.symbolContext("Pay 3 :go", 9), { typed: "go", start: 6, closed: false });
  assert.equal(core.symbolContext("effet:", 6), null);           // a field, not a symbol
  assert.equal(core.symbolContext(": ", 1), null);                // a definition line
  assert.equal(core.symbolContext("at 10:3", 7), null);
  assert.deepEqual(core.symbolAt("Pay :gold: now", 6), { name: "gold", start: 4, end: 10 });
  assert.deepEqual(core.symbolAt("Pay 3:gold:", 7), { name: "gold", start: 5, end: 11 });
  assert.deepEqual(core.symbolContext("Pay 3:go", 8), { typed: "go", start: 5, closed: false });
  assert.equal(core.symbolAt("at 10:30: now", 5), null);
});

test("card pictures: hover shows the image:: field as a picture", () => {
  const text = "# Cards {#cards}\n\nGift\n: points:: 7\n  image:: media/gift.png\n  Give two cards.\n";
  const md = core.hoverText(text, "Gift", (p) => "file:///v/g/" + p);
  assert.equal(md, "**Gift**\n\n![](file:///v/g/media/gift.png|height=160)\n\n**points:** 7\n\nGive two cards.");
  assert.match(core.hoverText(text, "Gift"), /\*picture: media\/gift\.png\*/);
});

test("paths, value labels, parts that don't add up", () => {
  const t = "---\ncover: media/box.jpg\n---\n![a](media/x.png) ![b](https://e.com/y.png)\n`![c](media/code.png)`\n";
  assert.deepEqual(core.pathLinks(t).map((p) => [p.line, p.path]), [[1, "media/box.jpg"], [3, "media/x.png"]]);
  assert.deepEqual(core.pathLinks("---\ncover: false\n---\n"), []);
  assert.equal(core.valueLabel('{2p: 7, 3p: 6, "*": 5}'), "2p 7 · 3p 6 · * 5");
  assert.equal(core.valueLabel("100"), "100");
  const comps = "- 10x [[a]]\n  - 6x [[b]]\n  - 4x [[c]]\n- 5x [[d]]\n  - 2x [[e]]\n  - 2x [[f]]\n    - 1x [[g]]\n";
  assert.deepEqual(core.inlineHints(comps, []).map((h) => [h.line, h.label]), [[3, "parts: 4 ≠ 5"]]);
});
