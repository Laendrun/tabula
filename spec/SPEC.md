# Tabula — specification v0.8 (draft)

A plain-text format for board, card, dice, dexterity, outdoor and homemade games. Each game is a single `.game` file: a game description and its rules, written in Markdown with three small additions.

> *Tabula* is Latin for "board" or "tablet", and it is also the name of an ancient Roman board game. The reference CLI is called `tabula`.

---

## 1. Design goals

1. **It's Markdown.** A `.game` file is valid Markdown. It reads well as raw text, and Markdown tools (GitHub, editors, Obsidian) render it nicely.
2. **A few small additions** on top of Markdown:
   - `[[references]]` to components and game terms
   - `{conditions}` for player counts and variants
   - definitions for the glossary
3. **Player-count aware.** Any part of the rules can apply only to certain player counts, variants or extensions, so a tool can show "the rules for 2 players with the Supercharge extension" and nothing else.
4. **One file per game**, with optional translations.
5. **Grow from real use.** Features get added once real games need them. See section 9 for ideas.

---

## 2. Files and folders

### 2.1 The vault

```
my-games/                       ← the vault
├── vault.yaml                  ← optional settings
├── _shared/                    ← shared fragments, included by games (see 10)
│   ├── deck-52.game
│   └── deck-52.fr.game
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
- Folders whose name starts with `_` (like `_shared/`) or `.` are never games.

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
| `variants` | map name → description, or list | `{omnibus: "…"}` | declares variants (other ways to play the same box), usable in `{+name}` conditions |
| `extensions` | map name → description, or list | `[supercharge, pandora]` | declares extensions/expansions (extra boxes), usable in `{+name}` conditions, see 8.5 |
| `location` | text | `Armoire de l'entrée` | where the game is stored |
| `cover` | path | `media/box.jpg` | the box image, relative to the game folder. Optional: without it (or with `cover:` left empty), the image called `cover` or `<slug>_cover` in the game's `media/` folder is used (`cover.jpg`, `skyjo_cover.png`…; for a standalone game, only `<slug>_cover`). `cover: false`: no cover |
| `links` | map | `{bgg: https://…}` | |
| `source` | text | `Rulebook 2nd ed.` | where the rules come from |
| `require_definitions` | true/false | `true` | `tabula check`: every component needs a glossary definition (see 5) |
| `unused_definitions` | true/false | `false` | `tabula check`: warn about definitions nothing refers to (default `true`, see 5) |

Count ranges: `4`, `2-5`, `3+`, `2,4`. Unknown keys are allowed and kept, so add your own.

---

## 4. Markdown you can use

All the usual Markdown: headings `#` to `######`, paragraphs, `*italic*` and `**bold**`, lists (`-`, `*`, `1.`), `> quotes` (shown as notes or tips), tables, images `![caption](media/photo.jpg)`, links, and fenced code blocks.

**Comments** use standard HTML comments, which are never shown:

```markdown
<!-- TODO: check the 5-player setup -->
```

A comment that starts with `TODO` or `FIXME` (any case, with or without `:`) is a **reminder**. `tabula todo` lists them for the whole vault, or for some games, with file and line. `tabula check` counts them without treating them as warnings, and editors show them as information.

**Continuing a list item:** indent the extra lines under the item, with no blank line in between:

```markdown
1. Choisissez une carte et ajoutez-la à votre collection.
   Classez vos cartes par série.
```

**Continuing a numbered list** after a table or paragraph: start the next item with the number you want (`3.`). Tools keep counting from there, and renumber when filtering hides steps.

**Ending a section:** a line with only `---` (three or more dashes) ends the current section. What follows belongs to the section around it again, with that section's role and condition. Tools show a small separator in its place.

```markdown
# Glossaire {#glossary}

## Cartes à jouer {#cards}

Cartes numérotées
: …

---

Effet                    ← back in "Glossaire": a glossary term, not a card
: …
```

Each `---` closes one level, so two in a row close two. After a top-level `#` section, `---` leaves the text outside any section. A `---` that only closes a section hidden by filtering (`## Deux joueurs {2p}` with `-p 4`) is not shown.

---

## 5. Addition 1: references `[[ ]]`

Double square brackets refer to a **component** or a **glossary term**. Names can have spaces, accents and hyphens:

```markdown
Mélangez la [[carte Machine à laver]] avec 10 [[cartes Chaussettes]].
Une [[Super-Chaussette]] compte comme n'importe quelle [[série]].
```

- **Matching** ignores case and plural endings (`s`, `x`) on every word, so `[[cartes Chaussettes]]` matches the component `carte Chaussette`.
- **An alias** shows different text but points to the given name: `[[série|séries complètes]]`.
- `tabula check` warns about references that match nothing. A component counts as known even without a glossary entry, since simple pieces like "deck" or "string" rarely need one. To require a definition for every component, use `tabula check --definitions`, or turn it on for the whole vault in `vault.yaml`:

  ```yaml
  check:
    require_definitions: true
  ```

  (or `require_definitions: true` in one game's frontmatter).
- `tabula check` also warns about **definitions that nothing refers to**, so a long glossary doesn't collect forgotten terms. Links to sections (`[[#…]]`) don't count, and cards in a catalog (`{#cards}`) are exempt, since the catalog lists them. Turn it off with `unused_definitions: false` in a game's frontmatter, or under `check:` in `vault.yaml`.
- Renderers show the visible text, highlighted. The HTML export makes it a link to the term, with its definition as a tooltip.

**Links to a section** start with `#`: `[[#Si la tour tombe]]` points to the heading with that title, matched the same way (case, accents and plurals ignored). It can also name a role: `[[#setup]]`. An alias works too: `[[#Si la tour tombe|cette section]]`.

```markdown
Si la tour tombe pendant ton tour, voir [[#Si la tour tombe]].
```

`tabula show` writes it `→ Si la tour tombe`, and the HTML export makes it a link to the section. `tabula check` warns when no heading matches. If filtering hides the section (`## Si la tour tombe {2p}` with `-p 4`), the text is shown without a link.

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

- The format is `N x [[name]] free text…`. `×` and `X` are accepted too, the space before `x` is optional, and `N` may be a range (`2-3x`). Words may come before the reference (`8x cartes [[Gift]]`): the first `[[…]]` on the line is the component.
- Write the name **in the singular**. References in the rules can use the plural.
- Declarations can go anywhere, but the convention is one section near the top.
- A component can be listed more than once. Each line can have its own condition: `{4p} 2x [[petite pierre]]` above means "2 more for 4 players".
- Any other list item is just text. "Prenez 10 [[cartes]]" doesn't declare anything.
- **Nested component lists break a component down.** Indented components are *part of* the one above them, not extra pieces:

  ```markdown
  - 125x [[carte à jouer]]
    - 81x [[carte numérotée]]
    - 44x [[carte spéciale]]
  ```

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

- **The definition body is ordinary Markdown.** Everything indented under the term (2 spaces or more) belongs to it: paragraphs, nested lists, `> notes`, key rules, even conditions.
- The first `:` line can be empty when the definition starts with a list, or the list can start on it:

  ```markdown
  Cartes numérotées
  :
    - Cartes de couleur
      - Se posent sur le même chiffre ou la même couleur.
    > **Remarque** : le noir n'est pas une couleur !

  Effet
  : - [[Gift]]
    - [[Skip]]
  ```
- **A term can have a condition**, before or after it, for example a card that only exists in an extension: `{+supercharge} Recharge` or `Recharge {+supercharge}`.
- Defined terms can be referenced with `[[term]]`. The term itself is written without brackets (`Black Hole`, not `[[Black Hole]]`).
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
| `+omnibus` | when the variant or extension `omnibus` is on |
| `-omnibus` | when it is off |
| `*` | otherwise (only inside inline choices; for a whole line shown only without an option, use `{-name}`) |

Codes are combined with spaces: `{4p +teams}`. Names must be declared in the frontmatter, under `variants:` or `extensions:`. They are **opt-in**: their content is hidden unless you turn them on (or ask for everything).

### 8.1 Where conditions go

**On a heading.** The condition covers the whole section, up to the next heading of the same or a higher level:

```markdown
## Passe {4p}
## Jeu en équipe {+teams}
```

**At the start or the end of a block.** The condition covers that one paragraph, list item, note, key rule or table row. A line starting with `{…}` always starts a new block.

```markdown
{2p} Asseyez-vous côte à côte.
- {3-5p} Donnez l'autre carte à votre voisin.
- 10x [[carte spéciale]] {+supercharge}
```

**Nested content follows its list item.** If a list item is hidden, everything indented under it is hidden too: sub-items, tables, notes and paragraphs.

```markdown
- 15x [[carte à jouer]] {+supercharge}     ← hidden without supercharge…
  - 5x [[carte numérotée]]                 ← …and so are these
  - 10x [[carte spéciale]]
```

**Inline choice.** Inside a sentence, list the alternatives as `code: text`, separated by `|`. The first matching alternative is shown. `*` is the fallback, and if nothing matches, nothing is shown.

```markdown
Distribuez {3p: 17 | 4p: 13 | 5p: 10} cartes.
Chaque joueur reçoit {2p: 3 pierres | *: 2 pierres}.
Le valet de carreau vaut {+omnibus: -10 points | *: 0 point}.
```

A single alternative works as an inline "only if": `Prenez une carte{+quick: , puis passez}.`

**What a reader sees.** By default, a game is shown as the **base game**: no extensions and no variants. Anything the reader hasn't decided stays visible with a badge. Without a player count, for example, you see `[2p]` and `⟨3p: 17 | 4p: 13⟩`. Choosing a player count (`-p 4`) or turning on extensions and variants (`-e`, `-v`) resolves those conditions: content that doesn't apply disappears, and the badges go away. `--all` shows every extension and variant with badges. Numbered lists are renumbered and empty sections are hidden.

### 8.2 Player tables

A table whose header cells, after the first one, are all player codes is a **player table**. Filtering keeps only the matching column:

```markdown
| Joueurs           | 3p | 4p | 5p |
|-------------------|----|----|----|
| Cartes par joueur | 17 | 13 | 10 |
```

The first header cell is free text, so you can write it in any language. Table rows can also start with a condition: `| {+omnibus} Valet de carreau | … |`.

The table can also be the other way round, with player codes **in the first column**. Filtering then keeps only the matching rows:

```markdown
| Joueurs | court | moyen | long |
|---------|-------|-------|------|
| 2-4p    | 137   | 154   | 179  |
| 5-8p    | 113   | 137   | 154  |
```

### 8.3 Key rules `!`

A line, or a list item, that starts with `! ` is a **key rule**. Key rules are highlighted and collected for cheat sheets:

```markdown
! La partie s'arrête dès que la Machine à laver est piochée.
- ! Seuls les effets des cartes gardées s'appliquent.
```

**A key section** is a heading that starts with `!`. Use it when what matters is a whole procedure rather than one rule. Everything under the heading belongs to it, sub-sections included, until the next heading of the same or a higher level (or its `---`):

```markdown
## ! Si la tour tombe {2-4p}

1. Arrêtez la partie.
2. Celui qui l'a fait tomber perd.
```

The `!` can be combined with conditions and roles. `tabula show` marks the heading with ★, and the HTML export frames the whole section like a key rule.

**Cheat sheet:** `tabula show GAME --key` shows only the key rules and key sections, under the headings they belong to, with the usual filters (`tabula show hearts --key -p 4`). `tabula export GAME --key` makes the same thing as a page to print.

### 8.4 Escaping

Use `\[[`, `\{` and `\!` (at the start of a line) to write those characters literally. Curly braces that don't contain valid codes are shown as normal text. `tabula check` warns when they look like a broken condition.

### 8.5 Extensions (expansions)

Declare the extensions in the frontmatter. Add a description if you want one shown:

```yaml
extensions:
  supercharge: "Cartes Puissance"
  troublemaker: "Nouvelles cartes spéciales et événements"
```

Then write each extension's content in the same file, with `{+name}`. Extensions come in two kinds, and both use the same tools.

**Additions** (more cards, new rules, new events):

```markdown
# Matériel
- 125x [[carte à jouer]]
- {+supercharge} 30x [[carte Puissance]]

# Supercharge {+supercharge}
Les [[cartes Puissance]] se jouent…

# Glossaire
Carte Puissance {+supercharge}
: …
```

**Changes to existing rules.** Write the base version with `{-name}` and the extension's version with `{+name}`. The base version is shown without the extension, the new one with it:

```markdown
- {-pandora} Distribuez 7 cartes à chaque joueur.
- {+pandora} Distribuez 7 cartes à chaque joueur, puis …

## Fin de la manche {-troublemaker}
…
## Fin de la manche {+troublemaker}
…
```

For a small change inside a sentence, use an inline choice: `Distribuez {+troublemaker: 9 | *: 7} cartes.`

`tabula show frantic` shows **the base game**. Add extensions with `-e` (`tabula show frantic -e pandora`), or see everything at once, with badges, using `tabula show frantic --all`.

When you show a game with extensions turned on (`tabula show frantic -e supercharge`), everything they add or change is **highlighted**: marked `[+supercharge]` and coloured, including nested parts and inline choices. Without filters, all conditions are shown as `[…]` badges instead.

Several extensions can be on at the same time (`-e supercharge -e pandora`). Combined codes cover rules that only apply to a combination: `{+supercharge +pandora}`.

Convention: keep the base rules first and readable, put each extension's new rules in its own section at the end, and use `{-name}`/`{+name}` pairs only where an extension really replaces a base rule.

---

## 9. Section roles

Headings are written in the game's language, so tools can't rely on their text. A **role** tells tools what a section contains. Write it as `#name` in the heading's braces:

```markdown
# Matériel {#components}
# Mise en place {#setup}
# Glossaire {#glossary}
## Cartes Puissance {+supercharge #cards}     ← a role and a condition together
```

Suggested roles: `components`, `goal`, `setup`, `play`, `scoring`, `end`, `glossary`, `cards`, `events`, `variants`, `notes`, `faq`. You can use your own names too. Roles are optional and a section can have several (`{#glossary #cards}`).

Tools use roles to show part of a game. `tabula show frantic -s glossary` shows only the glossary, and `-s components -s setup` shows two sections. Filters still apply. `-s` also accepts a heading's title (`-s "fin de la partie"`), so it works on games without roles too. Later, roles will let tools build cheat sheets, card catalogs and a web view with a table of contents.

### 9.1 Card catalog

Many games are mostly cards: special cards, events, power cards, and so on. A **card** is a glossary definition inside a section with the `#cards` role (sub-sections included):

```markdown
# Glossaire {#glossary}

## Cartes particulières {#cards}

{+troublemaker}Curse
: points:: 13
  type:: particulière
  Tu ne peux pas jouer cette carte.
  Mais tu peux l'offrir, l'échanger ou t'en débarrasser lors d'événements.

{+supercharge}Black Wish
: timing:: 2nd
  Tu souhaites le noir comme couleur.
```

- **Fields** are `key:: value` lines at the very top of the definition, before its text, in the same style as Obsidian Dataview. The keys are yours: `points`, `timing`, `type`, `colour`, `author`… Values can contain references and inline choices: `points:: {+points: 42}` shows the points only with the `points` variant, and a field whose value ends up empty is not shown.
- **A long value** continues on the next lines when they are indented deeper than the field. A line at the field's own indentation (the next field, or the text) or a blank line ends it:

  ```markdown
  8
  : effet:: Vous ne pouvez pas vous défausser d'un 8 s'il n'y a pas
      au moins 6 cartes dans la pile de défausse.
      Terminez immédiatement la manche.
    valeur:: 8
  ```
- **Counts come from the component list,** never from the card. Every line of the components section that names the card (`4x cartes [[Thief]]`, `{+pandora} 1x carte [[Thief]]`) is added up for the current selection, so the numbers stay right whatever extensions are on. A game without a component list can use a `count::` field instead.
- In a game without any `{#cards}` section, every definition that has fields counts as a card.
- `tabula cards GAME` prints the catalog: one row per card with its count and fields, grouped by sub-section, with an extension column when cards come from extensions. `--sort points` sorts across groups, and `--json` gives the data.
- `show` and `lookup` print the fields under the term. The HTML export shows them as small chips on each card, and puts a catalog table (linking to the cards) at the top of every `{#cards}` section.
- `tabula check` warns about empty fields, fields written twice, `key::` lines below the text (where they'd be read as text), and a card missing a field that most cards in its group have.

---

## 10. Shared fragments `![[ ]]`

Many games use the same things: a standard 52-card deck, a tarot deck, dice. Write them once in a **fragment**, a `.game` file in the vault's `_shared/` folder, and include it in each game:

```markdown
# Matériel {#components}

![[deck-52#Matériel]]
- 1x [[bloc de score]]

# Glossaire {#glossary}

![[deck-52#Glossaire]]

Bloc de score
: …
```

- **A fragment** is written like a game, with the same syntax: sections, components, definitions, conditions. Frontmatter is optional and not used by the game (a `title:` is a good reminder of what it is).
- **`![[deck-52]]`**, alone on its line, inserts the whole of `_shared/deck-52.game`. **`![[deck-52#Glossaire]]`** inserts only the content of one section, found by its title (matched like references) or its role (`![[deck-52#glossary]]`), with its sub-sections but without its heading.
- **Headings nest where they land:** a fragment's `#` sections become sub-sections of the section the include is in, and a selected section's sub-sections become sub-sections there. After the included lines, the game's next lines are back in the game's section, as if the fragment's sections had been closed with `---`.
- **Indentation is kept:** an indented include puts the fragment's lines at that indentation, so components can become parts of a game's component (`- 1x [[boîte]]` then `  ![[deck-52#Matériel]]` on the next line).
- **Translations:** a French game (`slug.fr.game`, or a game whose language is `fr`) includes `_shared/deck-52.fr.game` when it exists, else `_shared/deck-52.game`.
- **Conditions** inside a fragment are the game's: `{+jokers}` in the fragment needs `jokers` declared in the game that includes it, and follows its `-v jokers`.
- Fragments can include other fragments. A fragment that ends up including itself is an error.
- `tabula check` reports problems in included lines at the `![[…]]` line of the game, and checks each fragment on its own: syntax and TODOs only, since references and conditions depend on the game that includes it. `![[…]]` inside a sentence is an error: an include must be alone on its line.

## 11. Ideas for later (not part of v0.8)

These came up while designing. They'll be added once real games need them.

- **Printable card sheets:** cards from the catalog laid out at real card size, for sleeving or replacing lost cards.
- **Extension files:** large extensions in their own file next to the game (e.g. `frantic/frantic+pandora.game`) that is merged into the base game when the extension is on.
- **Extension metadata:** extensions that change the player count or duration (`extensions: {pandora: {players: 2-10}}`), or that require or exclude each other.
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

## 12. CLI (informative)

The reference CLI is `tabula`. Point it at a vault with `--vault PATH`, or set `$TABULA_VAULT`, or run it from inside the vault.

| Command | What it does |
|---|---|
| `tabula list [-p N] [-l CODE]` | list games, optionally only those playable with N players |
| `tabula show GAME [-p N] [-v VARIANT…] [-e EXTENSION…] [-a] [-s SECTION…] [-k] [-l CODE] [--json]` | print a game, by default the base game (no extensions or variants), filtered by player count, extensions, variants and language. `-a`/`--all` shows every extension and variant with badges. `-s` shows only some sections (role or title). `-k`/`--key` shows only the key rules and key sections (a cheat sheet). `--json` prints the parsed structure. |
| `tabula cards GAME [-p N] [-e …] [-v …] [-a] [-l CODE] [--sort COLUMN] [--json]` | the card catalog (section 9.1): one row per card, counts from the component list for the current selection, and fields as columns |
| `tabula lookup GAME [TERM] [-p N] [-e …] [-v …] [-a] [-l CODE] [--json]` | show one glossary term or component, for use at the table. Case, accents, plurals and small typos are ignored, and partial names work. Filters apply inside the definition. A term from an extension that isn't turned on is still shown, marked "only with +name". The output ends with "see also" for the terms it refers to. When no term has the exact name, it also looks for a section by role or title (`tabula lookup frantic components`). Without a term, lists every term. |
| `tabula export GAME [-p N] [-e …] [-v …] [-a] [-s SECTION…] [-k] [-l CODE] [-o FILE]` | write a self-contained HTML page with the same filtering as `show`: table of contents from the headings, glossary entries as cards, `[[references]]` as links with the definition as a tooltip, extension content highlighted, images embedded. Works offline, prints cleanly, and has a dark mode. The default file name describes the selection, e.g. `frantic-4p-supercharge.html`. `-k` exports the cheat sheet (`hearts-4p-key.html`). |
| `tabula site [-o FOLDER]` | write the whole vault as a small website (default folder: `site/`): an `index.html` listing every game, with filters for player count, duration and tags and a search, and for each game a page per language (`index.html`, `index.fr.html`) with every extension and variant marked, plus a cheat sheet (`key.html`) when it has key rules. On a game page, a bar lets the reader choose the player count and the extensions and variants (or everything): the page shows only what applies, like `tabula show`, picks the right text in inline choices, renumbers steps and updates card counts. The choice is kept in the address (`#p=4&o=pandora`), so a link opens the same view. Works offline from the folder, or on any static host. The folder is replaced on every run, but only if `tabula site` made it. |
| `tabula new SLUG [-t TITLE] [-p N] [-l CODE]` / `tabula new bgg ID [SLUG]` | start a game file: `<slug>/<slug>.game` with the frontmatter and the usual sections (with roles, headings in the game's language, a TODO in each). `new bgg ID` fills the frontmatter from BoardGameGeek (title, players, duration, age, year, designers, artists, publisher, box image saved as `media/cover.*`, found without a `cover:` line); `new bgg NAME` lists matching games and their IDs. Needs a BoardGameGeek token in `BGG_TOKEN`. Never replaces an existing game without `--force`. |
| `tabula todo [GAME…] [--json]` | list the `<!-- TODO: … -->` and `FIXME` reminders, with file and line, translations included. |
| `tabula check [GAME…] [--strict] [-d]` | find mistakes: frontmatter, references that match nothing, invalid or never-applying conditions, undeclared variants, missing images, duplicate terms, leftover v0.3 syntax, translation problems. Also checks the shared fragments in `_shared/`, warns about definitions nothing refers to, and counts TODO reminders (they never fail `--strict`). `-d`/`--definitions`: every component must also have a glossary definition. `--json`: the issues as JSON, with absolute paths. `--stdin`: check unsaved text for the one file given (used by editors) |

Planned: `new`, PDF export, `cheatsheet`, `server`.

---

## 13. Cheat sheet

```
---  frontmatter (YAML)  ---          title, players, variants, language…
# Heading  ## Sub                      Markdown headings
---                                    end of the current section (back to the one around it)
- 66x [[carte Chaussette]] — note      component declaration
[[name]]   [[name|shown text]]         reference to a component or term
Term                                   definition
: definition text
  - indented lines continue it
{2p} paragraph / - item {3-4p}         block condition (start or end of the line)
## Section {4p}   ## Variante {+quick} section condition
# Glossaire {#glossary}                section role (tabula show GAME -s glossary)
## Cartes {#cards}                     card catalog (tabula cards GAME)
Curse                                  card with fields
: points:: 13
{3p: 17 | 4p: 13 | *: 10}              inline choice
{-pandora} … / {+pandora} …            base rule / extension's replacement
| Joueurs | 3p | 4p |                  player table (or codes in the first column)
extensions: [supercharge]              in frontmatter; then {+supercharge}
! key rule                             cheat-sheet line
## ! Si la tour tombe                  key section (the whole section)
[[#Si la tour tombe]]                  link to a section (by title, or a role: [[#setup]])
![[deck-52#Glossaire]]                 include a shared fragment (_shared/deck-52.game), or one section of it
<!-- comment -->                       hidden
oh-my-socks.de.game                    translation
```
