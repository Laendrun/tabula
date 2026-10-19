# Tabula — specification v0.4 (draft)

A plain-text format for board, card, dice, dexterity, outdoor and homemade games. Each game is a single `.game` file: a game description and its rules, written in Markdown with three small additions.

> *Tabula* is Latin for "board" or "tablet", and it is also the name of an ancient Roman board game. The reference CLI is called `tabula`.

---

## 1. Design goals

1. **It's Markdown.** A `.game` file is valid Markdown. It reads well as raw text, and Markdown tools (GitHub, editors, Obsidian) render it nicely.
2. **Three small additions** on top of Markdown:
   - `[[references]]` to components and game terms
   - `{conditions}` for player counts and variants
   - definitions for the glossary
3. **Player-count aware.** Any part of the rules can apply only to certain player counts or variants, so a tool can show "the rules for 2 players" and nothing else.
4. **One file per game**, with optional translations.
5. **Grow from real use.** Features get added once real games need them. See section 9 for ideas.

---

## 2. Files and folders

### 2.1 The vault

```
my-games/                       ← the vault
├── vault.yaml                  ← optional settings
├── oh-my-socks/
│   ├── oh-my-socks.game        ← the game (description + rules)
│   ├── oh-my-socks.de.game     ← German translation (optional)
│   └── media/                  ← images, scans, score sheets…
│       └── box.jpg
└── crazy-eights.game           ← a "standalone" game: no folder needed
```

- **One game = one `.game` file.** It holds the description *and* the rules.
- **The id (slug)** is the file name without extension: `oh-my-socks`. Use lowercase with dashes.
- **Folder or standalone.** A game can live in its own folder, `<slug>/<slug>.game`, which gives it room for `media/` and other files. A game with no extra files can be a single `<slug>.game` directly in the vault.
- In a game folder, other files are ignored by tools, so you can keep notes, PDFs and anything else there.

### 2.2 `vault.yaml` (optional)

```yaml
name: Family games
language: fr        # default language of the .game files (default: en)
```

### 2.3 Languages

- **Default language.** A game's default language is the `language` key in its frontmatter. If that's missing, it's the vault's `language`, and if that's missing too, it's `en`.
- **Translations** are separate files with a language code before `.game`, e.g. `oh-my-socks.de.game` or `oh-my-socks.pt-BR.game`. They sit next to the default file, which is always required.
- **Frontmatter is merged.** A translation's frontmatter is merged over the default one, so it only needs what changes: `title`, variant descriptions, and so on. `players`, `duration`, `age`, `cover` and similar keys are inherited. Changing them in a translation produces a warning.
- **Identifiers are never translated.** Condition codes (`2p`, `+omnibus`) and variant names stay the same in every language. Everything a reader sees is translated, including component names and glossary terms.
- **Fallback.** Asking for a language a game doesn't have shows the default language, with a notice.

---

## 3. File structure

```markdown
---
title: Oh My Socks!
players: 2-5
variants:
  quick: "Partie rapide : retirez la moitié des séries"
---

# Matériel
- 66x [[carte Chaussette]] — 11 séries
- 1x [[carte Machine à laver]]

# But du jeu
…

# Mise en place
1. Distribuez {2p: 7 | *: 5} cartes à chaque joueur.
…

# Glossaire
Série
: Toutes les cartes du même motif.
```

1. **YAML frontmatter** between `---` lines at the very top.
2. **A Markdown body.** Headings, sections and their order are entirely up to you.

### 3.1 Frontmatter keys

| Key | Type | Example | Notes |
|---|---|---|---|
| `title` | text | `Oh My Socks!` | **required** |
| `players` | count range | `2-5` | **required** |
| `best_players` | count range | `4` | |
| `duration` | minutes | `15`, `30-60` | |
| `age` | number | `8` | meaning "8 and up" |
| `type` | list | `[card, dexterity]` | suggested values: `board`, `card`, `dice`, `dexterity`, `party`, `word`, `outdoor`, `homemade` |
| `tags` | list | `[family, quick]` | free |
| `designer` | text or list | `[Antoine Bauza]` | |
| `artist` | text or list | `[Camille Chaussy]` | |
| `publisher` | text | | |
| `year` | number | `2019` | |
| `language` | code | `fr` | default language of this game (overrides the vault) |
| `variants` | map name → description | `{omnibus: "…"}` | declares the variants usable in `{+name}` conditions |
| `location` | text | `Armoire de l'entrée` | where the game is stored |
| `cover` | path | `media/box.jpg` | relative to the game folder |
| `links` | map | `{bgg: https://…}` | |
| `source` | text | `Rulebook 2nd ed.` | where the rules come from |

Count ranges: `4`, `2-5`, `3+`, `2,4`. Unknown keys are allowed and kept, so add your own.

---

## 4. Markdown you can use

All the usual Markdown: headings `#` to `######`, paragraphs, `*italic*` and `**bold**`, lists (`-`, `*`, `1.`), `> quotes` (shown as notes or tips), tables, images `![caption](media/photo.jpg)`, links, and fenced code blocks.

**Comments** use standard HTML comments, which are never shown:

```markdown
<!-- TODO: check the 5-player setup -->
```

**Continuing a list item:** indent the extra lines under the item, with no blank line in between:

```markdown
1. Choisissez une carte et ajoutez-la à votre collection.
   Classez vos cartes par série.
```

---

## 5. Addition 1: references `[[ ]]`

Double square brackets refer to a **component** or a **glossary term**. Names can have spaces, accents and hyphens:

```markdown
Mélangez la [[carte Machine à laver]] avec 10 [[cartes Chaussettes]].
Une [[Super-Chaussette]] compte comme n'importe quelle [[série]].
```

- **Matching** ignores case and plural endings (`s`, `x`) on every word, so `[[cartes Chaussettes]]` matches the component `carte Chaussette`.
- **An alias** shows different text but points to the given name: `[[série|séries complètes]]`.
- `tabula check` warns about references that match nothing.
- Renderers show the visible text, highlighted. The web view will later make it a link or tooltip.

---

## 6. Addition 2: components

Components are declared as **list items that start with a quantity, then `x`, then a reference**:

```markdown
# Matériel
- 66x [[carte Chaussette]] — 11 séries ; dont 9 [[Cadeau]] et 9 [[Sauvetage]]
- 1x [[carte Machine à laver]]
- 1x [[ficelle]] (3 m, rouge)
- {4p} 2x [[petite pierre]] (paire en plus)
```

- The format is `N x [[name]] free text…`. `×` and `X` are accepted too, the space before `x` is optional, and `N` may be a range (`2-3x`).
- Write the name **in the singular**. References in the rules can use the plural.
- Declarations can go anywhere, but the convention is one section near the top.
- A component can be listed more than once. Each line can have its own condition: `{4p} 2x [[petite pierre]]` above means "2 more for 4 players".
- Any other list item is just text. "Prenez 10 [[cartes]]" doesn't declare anything.

---

## 7. Addition 3: definitions (glossary)

Definitions use the common "definition list" form: the term on its own line, then a line starting with `: `.

```markdown
Série
: Toutes les cartes Chaussettes du même motif.

Super-Chaussette
: Ajoutez-la à la série de votre choix ; elle ne rapporte aucun point.
  - Si c'est votre première chaussette, la suivante détermine son motif.
  - Reçue en [[Cadeau]], vous choisissez sa série en fin de partie.
: Une deuxième ligne `: ` ajoute un autre paragraphe.
```

- Indented lines (2 spaces or more) continue the definition, and that includes lists.
- Defined terms can be referenced with `[[term]]`.
- `tabula check` warns about terms that are defined twice.

---

## 8. Addition 4: conditions `{ }`

A condition is a set of **codes** in curly braces. Every code must hold.

| Code | Meaning |
|---|---|
| `2p` | exactly 2 players |
| `3-4p` | 3 or 4 players |
| `5+p` | 5 or more players |
| `3,5p` | 3 or 5 players |
| `!2p` | any number of players except 2 |
| `+omnibus` | when the variant `omnibus` is on |
| `-omnibus` | when the variant `omnibus` is off |
| `*` | otherwise (only inside inline choices) |

Codes are combined with spaces: `{4p +teams}`. Variants must be declared in the frontmatter (`variants:`). Variants are **opt-in**: when you filter, variant content is hidden unless you turn the variant on.

### 8.1 Where conditions go

**On a heading.** The condition covers the whole section, up to the next heading of the same or a higher level:

```markdown
## Passe {4p}
## Jeu en équipe {+teams}
```

**At the start of a block.** The condition covers that one paragraph, list item, note, key rule or table row. A line starting with `{…}` always starts a new block.

```markdown
{2p} Asseyez-vous côte à côte.
- {3-5p} Donnez l'autre carte à votre voisin.
```

**Inline choice.** Inside a sentence, list the alternatives as `code: text`, separated by `|`. The first matching alternative is shown. `*` is the fallback, and if nothing matches, nothing is shown.

```markdown
Distribuez {3p: 17 | 4p: 13 | 5p: 10} cartes.
Chaque joueur reçoit {2p: 3 pierres | *: 2 pierres}.
Le valet de carreau vaut {+omnibus: -10 points | *: 0 point}.
```

A single alternative works as an inline "only if": `Prenez une carte{+quick: , puis passez}.`

Without filters, tools show everything and mark conditions, like `[2p]` or `⟨3p: 17 | 4p: 13⟩`. With `--players 4` and/or `--variant X`, content that doesn't match disappears and the markers are removed. Numbered lists are renumbered.

### 8.2 Player tables

A table whose header cells, after the first one, are all player codes is a **player table**. Filtering keeps only the matching column:

```markdown
| Joueurs           | 3p | 4p | 5p |
|-------------------|----|----|----|
| Cartes par joueur | 17 | 13 | 10 |
```

The first header cell is free text, so you can write it in any language. Table rows can also start with a condition: `| {+omnibus} Valet de carreau | … |`.

### 8.3 Key rules `!`

A line, or a list item, that starts with `! ` is a **key rule**. Key rules are highlighted and collected for cheat sheets:

```markdown
! La partie s'arrête dès que la Machine à laver est piochée.
- ! Seuls les effets des cartes gardées s'appliquent.
```

### 8.4 Escaping

Use `\[[`, `\{` and `\!` (at the start of a line) to write those characters literally. Curly braces that don't contain valid codes are shown as normal text. `tabula check` warns when they look like a broken condition.

---

## 9. Ideas for later (not part of v0.4)

These came up while designing. They'll be added once real games need them.

- **Card catalogs:** per-type cards with a count, an effect and an icon (Cadeau ×9, Sauvetage ×9), rendered as a reference sheet.
- **Expansions and modules:** content that only applies when an expansion is present, e.g. `{+seafarers}` with `expansions:` in frontmatter, or a separate `catan+seafarers.game` that extends the base game.
- **Shared fragments:** one definition of "standard 52-card deck" included by many card games.
- **Roles and factions:** rules for asymmetric games, e.g. `{@wizard}` and `--role wizard`.
- **Solo and co-op:** `{1p}` already works. Solo bots or automata may need more structure.
- **Turn structure:** marking phases (`## Tour {phase}`) to generate a turn-summary card.
- **Scoring:** a declared score sheet (categories, per-player columns) for a printable score pad.
- **Player-count expressions:** text computed from the player count, like "deal {= 2 * n} cards".
- **Teaching:** marking sections as `{teach}` to produce a 2-minute teaching version.
- **FAQ, errata and house rules:** sections that are always shown but marked as such, perhaps `{house}`.
- **Icons:** short codes like `:star:` or `:coin:` rendered as game symbols.
- **Collection data:** wishlist or owned, lent to, missing pieces (a checklist built from the component list).
- **Play log:** date, players, scores, winner, used for statistics and "what haven't we played lately?".
- **Links between games:** `[[game:catan]]`, linking an expansion to its base game.

---

## 10. CLI (informative)

The reference CLI is `tabula`. Point it at a vault with `--vault PATH`, or set `$TABULA_VAULT`, or run it from inside the vault.

| Command | What it does |
|---|---|
| `tabula list [-p N] [-l CODE]` | list games, optionally only those playable with N players |
| `tabula show GAME [-p N] [-v VARIANT…] [-l CODE] [--json]` | print a game filtered by player count, variants and language. `--json` prints the parsed structure. |
| `tabula check [GAME…] [--strict]` | find mistakes: frontmatter, references that match nothing, invalid or never-applying conditions, undeclared variants, missing images, duplicate terms, leftover v0.3 syntax, translation problems |

Planned: `new`, `export --pdf`, `cheatsheet`, `server`.

---

## 11. Cheat sheet

```
---  frontmatter (YAML)  ---          title, players, variants, language…
# Heading  ## Sub                      Markdown headings
- 66x [[carte Chaussette]] — note      component declaration
[[name]]   [[name|shown text]]         reference to a component or term
Term                                   definition
: definition text
  - indented lines continue it
{2p} paragraph / - {3-4p} item         block condition
## Section {4p}   ## Variante {+quick} section condition
{3p: 17 | 4p: 13 | *: 10}              inline choice
| Joueurs | 3p | 4p |                  player table
! key rule                             cheat-sheet line
<!-- comment -->                       hidden
oh-my-socks.de.game                    translation
```
