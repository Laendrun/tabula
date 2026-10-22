const test = require("node:test");
const assert = require("node:assert/strict");
const core = require("../src/core");

/** Apply edits (same format as renameEdits / quickFixes) to a text. */
function apply(text, edits) {
  const lines = text.split("\n");
  for (const e of [...edits].sort((a, b) => b.line - a.line || b.start - a.start)) {
    const l = lines[e.line] || "";
    lines[e.line] = l.slice(0, e.start) + e.text + l.slice(e.end);
  }
  return lines.join("\n");
}

const GAME = `---
title: G
players: 2
---
# How to play {#play}

Move a [[bateau]], then two [[bateaux]] and a [[Bateau|navire]]. See [[#Tide rules]] and [[#play]].

## Tide rules

Every [[Bateau]] floats. \`[[Bateau]]\` in code stays.

# Glossary {#glossary}

Bateau {2p}
: A boat.

## Cards {#cards}

Gust
: effect:: wind
`;

test("rename a term from a reference: definition, case, plurals and aliases", () => {
  const line = 6, col = GAME.split("\n")[6].indexOf("bateau]]") + 2;
  const target = core.renameTarget(GAME, line, col);
  assert.equal(target.placeholder, "Bateau");
  const out = apply(GAME, core.renameEdits(GAME, line, col, "Navire"));
  assert.match(out, /Move a \[\[navire\]\], then two \[\[Navire\|bateaux\]\] and a \[\[Navire\|navire\]\]/);
  assert.match(out, /Every \[\[Navire\]\] floats\. `\[\[Bateau\]\]` in code stays\./);   // same line: code untouched?
  assert.match(out, /\nNavire \{2p\}\n: A boat\./);
});

test("rename from the definition line", () => {
  const out = apply(GAME, core.renameEdits(GAME, 14, 0, "Boat"));
  assert.match(out, /\nBoat \{2p\}\n/);
  assert.match(out, /Move a \[\[boat\]\]/);
});

test("rename a heading and the links to it, not role links", () => {
  const out = apply(GAME, core.renameEdits(GAME, 8, 4, "Tides"));
  assert.match(out, /## Tides\n/);
  assert.match(out, /See \[\[#Tides\]\] and \[\[#play\]\]/);
  const col = GAME.split("\n")[6].indexOf("#play");
  assert.throws(() => core.renameTarget(GAME, 6, col), /links to a role/);
});

test("rename refuses what it can't do", () => {
  assert.throws(() => core.renameEdits(GAME, 14, 0, "a|b"), /can't be empty/);
  assert.throws(() => core.renameEdits(GAME, 7, 0, "X"), /Put the cursor/);
  const g = "# Play\n\nUse [[deck]].\n";
  assert.throws(() => core.renameEdits(g, 2, 7, "Pack"), /isn't defined in this file/);
  // a term that is only a component is renamed everywhere
  const c = "# Components\n\n- 1x [[deck]]\n\nShuffle the [[deck]].\n";
  assert.equal(apply(c, core.renameEdits(c, 4, 15, "pack")), "# Components\n\n- 1x [[pack]]\n\nShuffle the [[pack]].\n");
});

test("quick fixes: spelling, frontmatter key, role, single brackets", () => {
  let f = core.quickFixes("Le délenche.", 0, "unknown word 'délenche' (did you mean 'déclenche'?)", { start: 3, end: 11 });
  assert.deepEqual(f.map((x) => x.title), ["Change to 'déclenche'", "Add 'délenche' to words.txt"]);
  assert.equal(apply("Le délenche.", f[0].edits), "Le déclenche.");
  assert.equal(core.quickFixes("x d'Eveline", 0, "unknown word 'd'Eveline'", { start: 2, end: 11 })[0].addWord, "Eveline");
  const fm = "---\ntitle: G\ndurantion: 10\n---\n";
  f = core.quickFixes(fm, 0, "'durantion:' in frontmatter: did you mean 'duration'? (other keys are kept as they are)", { start: 0, end: 3 });
  assert.equal(apply(fm, f[0].edits), "---\ntitle: G\nduration: 10\n---\n");
  f = core.quickFixes("## Cartes {#cartes}", 0, "role '#cartes': did you mean '#cards'? Tools only know '#cards'", { start: 0, end: 1 });
  assert.equal(apply("## Cartes {#cartes}", f[0].edits), "## Cartes {#cards}");
  f = core.quickFixes("Take a [Queen].", 0, "'[Queen]' has single brackets; write [[Queen]] to make it a reference", { start: 0, end: 1 });
  assert.equal(apply("Take a [Queen].", f[0].edits), "Take a [[Queen]].");
});

test("quick fixes: a reference that matches nothing", () => {
  const text = "# Play\n\nDraw a [[Grnde marée|big one]].\n\n# Glossaire {#glossary}\n\nGrande marée\n: Tide.\n\n## Cartes {#cards}\n";
  const msg = "[[Grnde marée|big one]] matches no component ('- 1x [[Grnde marée]]' in a list) and no definition";
  const f = core.quickFixes(text, 2, msg, { start: 7, end: 30 }, ["Grande marée", "Mer d'huile", "grande marée"]);
  assert.deepEqual(f.map((x) => x.title), ["Change to [[Grande marée]]", "Define 'Grnde marée' in the glossary"]);
  assert.match(apply(text, f[0].edits), /Draw a \[\[Grande marée\|big one\]\]\./);
  assert.match(apply(text, f[1].edits), /: Tide\.\n\nGrnde marée\n: \n\n## Cartes/);     // before the card catalog
  const s = core.quickFixes("See [[#Setpu]].", 0, "[[#Setpu]] matches no section (a heading titled 'Setpu', or a role like #setup)",
    { start: 4, end: 14 }, [], ["Setup", "Play"]);
  assert.deepEqual(s.map((x) => x.title), ["Change to [[#Setup]]"]);
});

test("images dropped or pasted: on a card, its picture; elsewhere, an inline image", () => {
  const t = "# Rules\n\nText.\n\n# Cards {#cards}\n\nGift\n: points:: 7\n  Give.\n\nSkip\n: Skip a turn.\n  More.\n\nOld\n: image:: media/old.png\n  X.\n\nEmpty\n:\n  - a list\n";
  assert.deepEqual(core.imagePlacement(t, 2, "media/x.png", "x"), { kind: "inline", text: "![x](media/x.png)" });
  let p = core.imagePlacement(t, 8, "media/cards/gift.png");
  assert.equal(p.term, "Gift");
  assert.match(apply(t, p.edits), /Gift\n: points:: 7\n  image:: media\/cards\/gift\.png\n  Give\./);
  p = core.imagePlacement(t, 11, "media/cards/skip.png");
  assert.match(apply(t, p.edits), /Skip\n: image:: media\/cards\/skip\.png\n  Skip a turn\.\n  More\./);
  p = core.imagePlacement(t, 15, "media/cards/new.png");
  assert.match(apply(t, p.edits), /Old\n: image:: media\/cards\/new\.png\n  X\./);
  p = core.imagePlacement(t, 19, "media/cards/e.png");
  assert.match(apply(t, p.edits), /Empty\n: image:: media\/cards\/e\.png\n  - a list/);
  assert.equal(core.imageFileName("Grande marée", ".png", ["grande-maree.png", "Grande-Maree-2.png"]), "grande-maree-3.png");
});
