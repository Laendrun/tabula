const test = require("node:test");
const assert = require("node:assert/strict");
const core = require("../src/core");
const { outlineOf } = require("./outline-helper");
const O = (text) => outlineOf(text).o;

/** Apply edits ({ line, start, end, text }) to a text. */
function apply(text, edits) {
  const lines = text.split("\n");
  for (const e of [...edits].sort((a, b) => b.line - a.line || b.start - a.start)) {
    const l = lines[e.line] || "";
    lines[e.line] = l.slice(0, e.start) + e.text + l.slice(e.end);
  }
  return lines.join("\n");
}

test("images dropped or pasted: on a card, its picture; elsewhere, an inline image", () => {
  const t = "# Rules\n\nText.\n\n# Cards {#cards}\n\nGift\n: points:: 7\n  Give.\n\nSkip\n: Skip a turn.\n  More.\n\nOld\n: image:: media/old.png\n  X.\n\nEmpty\n:\n  - a list\n";
  const o = O(t), lines = t.split("\n");
  assert.deepEqual(core.imagePlacement(o, lines, 2, "media/x.png", "x"), { kind: "inline", text: "![x](media/x.png)" });
  let p = core.imagePlacement(o, lines, 8, "media/cards/gift.png");
  assert.equal(p.term, "Gift");
  assert.match(apply(t, p.edits), /Gift\n: points:: 7\n  image:: media\/cards\/gift\.png\n  Give\./);
  p = core.imagePlacement(o, lines, 11, "media/cards/skip.png");
  assert.match(apply(t, p.edits), /Skip\n: image:: media\/cards\/skip\.png\n  Skip a turn\.\n  More\./);
  p = core.imagePlacement(o, lines, 15, "media/cards/new.png");
  assert.match(apply(t, p.edits), /Old\n: image:: media\/cards\/new\.png\n  X\./);
  p = core.imagePlacement(o, lines, 19, "media/cards/e.png");
  assert.match(apply(t, p.edits), /Empty\n: image:: media\/cards\/e\.png\n  - a list/);
  assert.equal(core.imageFileName("Grande marée", ".png", ["grande-maree.png", "Grande-Maree-2.png"]), "grande-maree-3.png");
});
