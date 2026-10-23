"use strict";
const test = require("node:test");
const assert = require("node:assert/strict");
const core = require("../src/core");
const { outlineOf } = require("./outline-helper");

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

test("outline: headings, definitions, components (from tabula outline)", () => {
  const { o, lines } = outlineOf(GAME);
  assert.deepEqual(o.headings.map((h) => [h.title, h.level, h.cond, h.roles]), [
    ["Components", 1, "", ["components"]], ["Glossary", 1, "", ["glossary"]], ["Cards", 2, "", ["cards"]],
    ["Two players", 2, "2p", []], ["Extra", 2, "", []],
  ]);
  assert.deepEqual(o.definitions.map((d) => [d.term, d.cond]), [["Gift", "+expo"], ["Card", ""], ["Effect", "+expo"]]);
  assert.deepEqual(o.components.map((c) => [c.name, c.quantity]), [["card", "60"], ["Gift", "10"]]);
  assert.equal(lines[o.definitions[0].end], "  Give two cards.");
  assert.deepEqual(o.references.map((r) => r.name), ["card", "Gift"]);        // not in code or comments
});

test("outline: '---' ends sections", () => {
  const { o, lines } = outlineOf(GAME);
  const byTitle = Object.fromEntries(o.headings.map((h) => [h.title, h]));
  assert.equal(lines[byTitle.Cards.end], "---");                        // closed by the first ---
  assert.equal(lines[byTitle.Extra.end], "---");                        // "Two players" was empty
  assert.equal(byTitle.Glossary.end, byTitle.Extra.end + 2);            // the second --- after Extra closes Glossary
  assert.equal(byTitle["Two players"].end, byTitle["Two players"].line);
});

test("reference under the cursor and its targets", () => {
  const line = "Shuffle the [[cards|deck]] and the [[Gift]].";
  assert.equal(core.refAt(line, 15).name, "cards");
  assert.equal(core.refAt(line, 3), null);
  const { o, lines } = outlineOf(GAME + "\nShuffle the [[cards|deck]], the [[gifts]] and [[nothing]].\n");
  const at = (name) => o.references.find((r) => r.name === name);
  assert.deepEqual(core.targets(o, at("cards")).map((t) => lines[t.line]), ["Card"]);       // the definition wins
  assert.deepEqual(core.targets(o, at("gifts")).map((t) => lines[t.line]), ["{+expo} Gift"]);
  assert.deepEqual(core.targets(o, at("nothing")), []);
  const r = at("cards");
  assert.equal(core.refUnder(o, r.line, r.start + 3), r);
});

test("key sections and section links", () => {
  const text = "# Play {#play}\n\nSee [[#When it falls|this]] and [[#setup]], [[#when it FALL]], [[#nowhere]].\n\n## ! When it falls {2p}\n\nStop.\n\n# Mise en place {#setup}\n\nX.\n";
  const { o, lines } = outlineOf(text);
  assert.deepEqual(o.headings.map((h) => [h.title, h.key]), [["Play", false], ["When it falls", true], ["Mise en place", false]]);
  const refs = o.references;
  assert.deepEqual(refs.map((r) => [r.name, r.section, r.alias]), [["When it falls", true, "this"], ["setup", true, null], ["when it FALL", true, null], ["nowhere", true, null]]);
  assert.deepEqual(core.targets(o, refs[2]).map((t) => lines[t.line]), ["## ! When it falls {2p}"]);
  assert.deepEqual(core.targets(o, refs[1]).map((t) => lines[t.line]), ["# Mise en place {#setup}"]);
  assert.deepEqual(core.targets(o, refs[3]), []);
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
  const { terms, sections } = core.completionsFor(outlineOf(SAMPLE).o);
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
  const { o } = outlineOf(SAMPLE + "\nSee [[cartes]], [[pion]], [[#si la tour tombe]], [[#glossary]], [[#déplacer le pion]], [[nothing]], [[#nothing]].\n");
  const [card, pion, tour, glossary, deplacer, nothing, nowhere] = o.references.slice(-7);
  const h = core.hoverFor(o, card);
  assert.match(h, /^\*\*Carte\*\* `\{\+expo\}`\n\n\*\*points:\*\* 3/);
  assert.match(h, /Doublon ignoré/);                   // both definitions are shown
  assert.match(h, /- 60x carte/);                      // and the component line
  assert.equal(core.hoverFor(o, pion), "- 2x Pion — rouges");
  assert.match(core.hoverFor(o, tour), /^\*\*★ Si la tour tombe\*\* `\{2p\}`\n\nArrête la partie, voir Carte\./);
  assert.match(core.hoverFor(o, glossary), /^\*\*Glossaire\*\*/);
  assert.match(core.hoverFor(o, deplacer), /^\*\*Déplacer le Pion\*\*\n\nTexte\./);
  assert.equal(core.hoverFor(o, nothing), null);
  assert.equal(core.hoverFor(o, nowhere), null);
});

test("TODO reminders are information, not warnings", () => {
  const S = { Error: 0, Warning: 1, Information: 2 };
  assert.equal(core.severity("error", S), 0);
  assert.equal(core.severity("warning", S), 1);
  assert.equal(core.severity("todo", S), 2);
  assert.equal(core.severity("spelling", S), 2);
});

test("include lines: under the cursor, while typing, hover", () => {
  assert.deepEqual(core.includeContext("![[de", 5), { name: "de", section: null, start: 3, closed: false });
  assert.deepEqual(core.includeContext("![[deck-52#Glo]]", 14), { name: "deck-52", section: "Glo", start: 11, closed: true });
  assert.equal(core.includeContext("[[de", 4), null);
  const frag = "# Components {#components}\n\n- 52x [[card]]\n\n# Glossary\n\nCard\n: One card.\n";
  const { o } = outlineOf("# K\n\n![[deck-52#components]]\n\n![[deck-52]]\n\n![[nope]]\n\nSee ![[deck-52]] here.\n",
    { files: { "_shared/deck-52.game": frag } });
  assert.deepEqual(o.includes.map((i) => [i.name, i.section, i.line, !!i.file]), [["deck-52", "components", 2, true], ["deck-52", "", 4, true], ["nope", "", 6, false]]);
  assert.equal(core.includeHover(o.includes[0]), "*from `_shared/deck-52` — components*\n\n- 52x card");
  assert.match(core.includeHover(o.includes[1]), /^\*from `_shared\/deck-52`\*\n\n# Components/);
  assert.equal(core.includeHover(o.includes[2]), "No shared fragment `nope` (looked for _shared/nope.game)");
  assert.deepEqual(o.fragments.map((f) => f.definitions.map((d) => d.term)), [["Card"]]);
});

test("a field can continue on indented lines", () => {
  const text = "# Cards {#cards}\n\n8\n: effet:: Vous ne pouvez pas\n    vous défausser d'un 8.\n    Terminez la manche.\n  valeur:: 8\n  Texte.\n";
  const { o } = outlineOf(text);
  assert.equal(core.definitionHover(o.definitions[0]),
    "**8**\n\n**effet:** Vous ne pouvez pas vous défausser d'un 8. Terminez la manche.  \n**valeur:** 8\n\nTexte.");
});

test("values: the game's, the default-language file's, the vault's; typing and hovering", () => {
  const vault = 'language: fr\nvalues:\n  target: 100\n  hand: {2p: 9, "*": 5}\n';
  const game = '---\ntitle: G\nplayers: 2-4\nvalues:\n  hand:\n    2p: 7\n    "*": 5\n  "max": 3   # comment\n---\n# Rules\n\nvalues:\n  not: frontmatter\n\nDeal {=hand} cards.\n';
  const { o } = outlineOf(game, { files: { "vault.yaml": vault } });
  assert.deepEqual(o.values.map((x) => [x.name, x.value, x.from]), [["hand", "2p 7 · * 5", "this file"], ["max", "3", "this file"], ["target", "100", "vault.yaml"]]);
  assert.deepEqual(o.hints.map((h) => [h.line, h.label]), [[14, "= 2p 7 · * 5"]]);
  const tr = outlineOf("---\ntitle: G (en)\n---\n# Rules\n\nDeal {=hand}.\n", { file: "g/g.en.game", files: { "vault.yaml": vault, "g/g.game": game } }).o;
  assert.deepEqual(tr.values.map((x) => [x.name, x.from]), [["hand", "the default-language file"], ["max", "the default-language file"], ["target", "vault.yaml"]]);
  assert.deepEqual(core.valueContext("Deal {=ha", 9), { typed: "ha", start: 7, closed: false });
  assert.equal(core.valueContext("Deal {=ha}", 9).closed, true);
  assert.equal(core.valueContext("Deal {2p: x", 11), null);
  assert.deepEqual(core.valueAt("Deal {=hand} cards", 8), { name: "hand", start: 5, end: 12 });
  assert.equal(core.valueAt("Deal {=hand} cards", 15), null);
});

test("symbols: definitions, typing and hovering", () => {
  const vault = 'symbols:\n  gold: media/gold.png\n  star: "⭐"\n';
  const game = '---\ntitle: G\nplayers: 2\nsymbols:\n  key: {image: media/key.png, text: "🔑"}\n  star: ★\n---\n# R\n';
  const { o, root } = outlineOf(game, { files: { "vault.yaml": vault } });
  assert.deepEqual(o.symbols.map((s) => [s.name, s.text, s.image && require("path").relative(root, s.image), s.from]), [
    ["key", "🔑", "g/media/key.png", "this file"], ["star", "★", null, "this file"], ["gold", null, "media/gold.png", "vault.yaml"],
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
  const { o } = outlineOf(text, { files: { "g/media/gift.png": "x" } });
  const md = core.definitionHover(o.definitions[0], (p) => "file://" + p);
  assert.match(md, /^\*\*Gift\*\*\n\n!\[\]\(file:\/\/.*g\/media\/gift\.png\|height=160\)\n\n\*\*points:\*\* 7\n\nGive two cards\.$/);
  assert.match(core.definitionHover(outlineOf(text).o.definitions[0], (p) => p), /\*picture: media\/gift\.png\*/);   // missing file
});

test("paths, parts that don't add up", () => {
  const t = "---\ntitle: T\nplayers: 2\ncover: media/box.jpg\n---\n![a](media/x.png) ![b](https://e.com/y.png)\n`![c](media/code.png)`\n";
  const { o } = outlineOf(t);
  assert.deepEqual(o.links.map((p) => [p.line, p.src, !!p.url]), [[5, "media/x.png", false], [5, "https://e.com/y.png", true], [3, "media/box.jpg", false]]);
  const comps = "# C\n\n- 10x [[a]]\n  - 6x [[b]]\n  - 4x [[c]]\n- 5x [[d]]\n  - 2x [[e]]\n  - 2x [[f]]\n    - 1x [[g]]\n";
  assert.deepEqual(outlineOf(comps).o.hints.map((h) => [h.line, h.label]), [[5, "parts: 4 ≠ 5"]]);
});

test("totals of a group: hover and inline hints", () => {
  const text = [
    "# Glossaire {#glossary}", "",
    "Attaque", ": avec::", "  sans::", "  type::", "  Toutes les attaques.",
    "  - [[Attaque 2x]]", "  - {+barking} [[Perso|personnelle]]", "",
    "Tout", ": avec::", "  - [[Attaque]]", "  - [[Passe]]", "",
    "Attaque 2x", ": avec:: 2", "  sans:: 3", "  type:: attaque", "  Texte.", "",
    "Passe", ": avec:: 4", "  Texte.", "",
    "## Barking {+barking}", "",
    "Perso", ": avec:: 1.5", "  type:: perso", "  Texte.", "",
  ].join("\n");
  const { o } = outlineOf(text);
  const hints = o.hints.filter((h) => h.label.startsWith("Σ"));
  assert.deepEqual(hints.map((h) => [h.line, h.label]),
    [[3, "Σ 3.5 (base game: 2)"], [4, "Σ 3"], [5, "Σ attaque, perso (base game: attaque)"], [11, "Σ 7.5 (base game: 6)"]]);
  assert.equal(hints[0].tooltip, "Attaque 2x: 2\nPerso: 1.5 (+barking)");
  assert.match(core.definitionHover(o.definitions[0]), /\*\*avec:\*\* Σ 3\.5 \(base game: 2\)  \n\*\*sans:\*\* Σ 3/);
  assert.match(core.definitionHover(o.definitions[2]), /\*\*avec:\*\* 2/);
});

test("the schemas in the extension are those of the spec", () => {
  const fs = require("fs");
  const path = require("path");
  for (const name of ["game", "sheet", "vault", "wishlist"]) {
    const here = fs.readFileSync(path.join(__dirname, "..", "schemas", `${name}.schema.json`), "utf8");
    const spec = fs.readFileSync(path.join(__dirname, "..", "..", "..", "spec", "schemas", `${name}.schema.json`), "utf8");
    assert.equal(here, spec, `${name}.schema.json: copy spec/schemas/*.json into editors/vscode/schemas/`);
  }
});

test("frontmatter levels", () => {
  const text = "---\ntitle: F\nplayers: 2\nvalues:\n  main: 3\nextensions:\n  pandora:\n    players: 2-10\n    \n---\n";
  const { o, lines } = outlineOf(text);
  assert.equal(core.frontmatterContext(o, lines[4], 4, 2), null);                  // under values: not a key of ours
  assert.deepEqual(core.frontmatterContext(o, lines[8], 8, 4), { level: "option", start: 4, present: ["players"] });
  assert.deepEqual(core.frontmatterContext(o, "pl", 2, 2).present, ["title", "values", "extensions"]);
  assert.equal(core.frontmatterContext(o, "", 10, 0), null);                  // after the frontmatter
  assert.deepEqual(core.frontmatterKeyAt(o, 7, 5), { level: "option", key: "players", start: 4, end: 11 });
});

test("columns: the outline counts characters, VS Code UTF-16 units", () => {
  const line = "🎲 [[dé]] x";
  assert.equal(core.u16(line, 2), 3);
  assert.equal(core.cp(line, 3), 2);
  const { o } = outlineOf("# R\n\n" + line + "\n\n# G {#glossary}\n\nDé\n: Un cube.\n");
  const r = o.references[0];
  assert.deepEqual([r.start, r.end], [2, 8]);
  assert.equal(core.u16(line, r.start), 3);
});
