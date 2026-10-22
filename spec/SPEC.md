# Tabula — specification v1.0

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
5. **Grow from real use.** Features get added once real games need them. See section 13 for ideas, and section 16 for what changed between versions.

---

## 2. Files and folders

### 2.1 The vault

```
my-games/                       ← the vault
├── vault.yaml                  ← optional settings
├── wishlist.yaml               ← games and extensions you'd like (optional, see 12)
├── _shared/                    ← shared fragments, included by games (see 10)
│   ├── deck-52.game
│   └── deck-52.fr.game
├── oh-my-socks/
│   ├── oh-my-socks.game        ← the game (description + rules)
│   ├── oh-my-socks.de.game     ← German translation (optional)
│   ├── oh-my-socks.sheet       ← a score sheet to print (optional, see 11)
│   └── media/                  ← images, scans…
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
values:             # values every game can use ({=target}, see 8.6); a game's own values win
  target: 100
symbols:            # symbols every game can use (:gold:, see 4)
  gold: media/gold.png
  star: ⭐
```

### 2.2.1 JSON Schemas

The keys of the frontmatter, of `vault.yaml`, of `wishlist.yaml` and of a `.sheet` file's frontmatter are also described as JSON Schemas (draft-07), in `spec/schemas/`: `game.schema.json`, `vault.schema.json`, `wishlist.schema.json` and `sheet.schema.json`. Editors use them for completion and checks (the VS Code extension does). They allow your own keys, like the format does; `tabula check` remains the reference.

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
| `year` | number | `2019` | the year the game came out; shown on its page, in `tabula show` and on the site |
| `language` | code | `fr` | default language of this game (overrides the vault) |
| `variants` | map name → description, or list | `{omnibus: "…"}` | declares variants (other ways to play the same box), usable in `{+name}` conditions |
| `extensions` | map name → description (or details), or list | `[supercharge, pandora]` | declares extensions/expansions (extra boxes), usable in `{+name}` conditions; details like `players`, `needs`, `excludes`: see 8.5 |
| `location` | text | `Armoire de l'entrée` | where the game is stored |
| `cover` | path | `media/box.jpg` | the box image, relative to the game folder. Optional: without it (or with `cover:` left empty), the image called `cover` or `<slug>_cover` in the game's `media/` folder is used (`cover.jpg`, `skyjo_cover.png`…; for a standalone game, only `<slug>_cover`). `cover: false`: no cover |
| `links` | map | `{bgg: https://…}` | |
| `source` | text | `Rulebook 2nd ed.` | where the rules come from |
| `require_definitions` | true/false | `true` | `tabula check`: every component needs a glossary definition (see 5) |
| `unused_definitions` | true/false | `false` | `tabula check`: warn about definitions nothing refers to (default `true`, see 5) |
| `spelling` | true/false | `false` | `tabula check`: check spelling in this game (`false` turns it off even with `--spell`, see 14) |
| `words` | list | `[Whitby, Lüthi]` | words the spell check should accept in this game (see 14) |
| `symbols` | map name → text or image | `{key: media/key.png}` | symbols written `:key:` in the text (see 4) |
| `values` | map name → value | `{main: {2p: 7, "*": 5}}` | values written `{=main}` in the text (see 8.6) |

Count ranges: `4`, `2-5`, `3+`, `2,4`.

**Your own keys.** Only the keys above do something. Any other key is allowed, kept, and shown as it is, as "Label: value", under the credits of the exported page and the book, and under the title in `tabula show` (and in `show --json`'s `meta`):

```yaml
series: Rulefactory          # shown as "Series: Rulefactory"
bought_at: Spiel 2019        # "Bought at: Spiel 2019" (underscores become spaces)
sleeved: true                # "Sleeved: yes"
```

A list is shown with commas, a mapping as "Key: value; …"; empty keys are left out. `tabula check` only warns about a key that is one or two letters away from a known one (`durantion:`).

---

## 4. Markdown you can use

All the usual Markdown: headings `#` to `######`, paragraphs, `*italic*` and `**bold**`, lists (`-`, `*`, `1.`), `> quotes` (shown as notes, or as callouts, see below), tables, images `![caption](media/photo.jpg)`, links, and fenced code blocks.

**Comments** use standard HTML comments, which are never shown:

```markdown
<!-- TODO: check the 5-player setup -->
```

A comment that starts with `TODO` or `FIXME` (any case, with or without `:`) is a **reminder**. `tabula todo` lists them for the whole vault, or for some games, with file and line. `tabula check` counts them without treating them as warnings, and editors show them as information.

**Callouts** are the boxes of a rulebook: examples, warnings, tips, clarifications. Start a `>` quote with `[!type]`, and an optional title:

```markdown
> [!exemple] Un tour à trois joueurs
> Alice joue un 7, Bob un 8…

> [!attention]
> Ne mélangez jamais la défausse.
```

- The type is written in the game's language. Tools know these families and draw each one its own way (color, icon): **example** (`exemple`, `example`, `beispiel`…), **warning** (`attention`, `important`, `warning`, `achtung`…), **tip** (`astuce`, `conseil`, `tip`, `tipp`, `stratégie`…), **info** (`précision`, `remarque`, `note`, `rappel`, `clarification`, `hinweis`…), **question** (`question`, `faq`, `frage`). Any other type works too and gets a neutral box.
- Without a title, the type is the title, with a capital: `[!astuce]` shows "Astuce".
- **Several paragraphs, or a list:** inside a quote (a callout or a plain note), a line with only `>` separates paragraphs, and `> - …` lines make a list. An item continues on the next lines indented under it, as anywhere else:

  ```markdown
  > [!astuce] Trois petites astuces
  > - Économisez vos cartes en début de partie.
  >
  > - Il n'y a pas de taille de main maximum.
  >   Si vous êtes à court de cartes, rien de spécial ne se produit.
  ```

  A quote with only plain lines is one paragraph, its lines joined.
- Conditions work as on any paragraph (`> {2p} …`, also on one paragraph or item inside a quote), and a callout can be nested in a list item. A plain `>` quote stays a simple note.

**Symbols** are the icons of a game: gold, keys, stars, card suits. Define them once, in `vault.yaml` for the ones many games share, or in a game's frontmatter, and write `:name:` in the text, in tables and in card fields:

```yaml
symbols:
  star: ⭐                                    # text: an emoji or a word
  gold: media/gold.png                       # an image: next to vault.yaml, or in the game's folder
  key: {image: media/key.png, text: "🔑"}     # an image, and the text the terminal shows instead
```

```markdown
Payez 3 :gold: et 1 :key: pour marquer 2 :star:.
```

- The site, the book and the HTML export draw an image symbol at the size of the text. The terminal writes its `text` (or its name). A text symbol is written as it is everywhere.
- A game's symbols win over `vault.yaml`'s, so a game can draw its own `:gold:`. Translations use the same symbols.
- Only defined names are replaced: `10:30:` or a `:word:` that is not a symbol stays as written, and so does `:gold:` in a code span. `tabula check` warns about a `:word:` that is close to a symbol's name (a typo), and about missing images.

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

A key rule can span several lines: the next lines continue it, with or without a `!` of their own (consecutive `!` lines are one rule, like consecutive `>` lines are one note). A blank line ends it, so two rules are separated by a blank line:

```markdown
! Un joueur ne peut pas commencer la partie avec 2 [[Reines]] ou plus en main.
! S'il en a 2, il remplace ses cartes ; s'il en a 3, la distribution est annulée.

! Une autre règle clé.
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

Use `\[[`, `\{` and `\!` (at the start of a line) to write those characters literally, and `\|` for a `|` inside a table cell (a `|` inside `[[Deck|the deck]]` doesn't split cells or choices). Curly braces that don't contain valid codes are shown as normal text. `tabula check` warns when they look like a broken condition.

### 8.5 Extensions (expansions)

Declare the extensions in the frontmatter. Add a description if you want one shown:

```yaml
extensions:
  supercharge: "Cartes Puissance"
  troublemaker: "Nouvelles cartes spéciales et événements"
```

Then write each extension's content in the same file, with `{+name}`. Extensions come in two kinds, and both use the same tools.

**Details:** an extension (or a variant) can say more than its description:

```yaml
extensions:
  troublemaker: "Nouvelles cartes spéciales et événements"
  pandora:
    description: "La boîte de Pandore"
    players: 2-10            # the player counts the game gets with it (added to the base game's)
    duration: 10-50
    year: 2016               # when it came out
    needs: [troublemaker]    # turned on with it
    excludes: [points]       # can't be used together
    box: blue                # your own: shown as "Box: blue"
```

- `players`: `tabula show frantic -p 10` is refused, but `-p 10 -e pandora` works, and `{9-10p}` conditions don't count as "never applies". `tabula list -p 10` lists the game with "(+pandora)", the site's player filter finds it, and its page shows "2–10 +pandora" and offers 9 and 10 players.
- `needs`: `-e pandora` also turns on troublemaker (and says so). `excludes`: asking for both is refused.
- A translation can give just a translated description (`pandora: "Pandora's box"`): the details come from the default-language file.
- `year`, your own details and the other details are listed with each extension and variant in the header of the exported page ("Extensions and variants") and the book, in the tooltip of its checkbox on an interactive page, and after its name in `tabula show`: "pandora (2016, 2-10p, needs troublemaker, Box: blue)".
- Other keys are your own, as in the frontmatter. `tabula check` warns about one that looks like a typo of a known detail (`playres:`), and reports invalid ranges, a `year` that isn't a year, and names in `needs`/`excludes` that aren't declared.

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

### 8.6 Values `{=name}`

A number or a word that depends on the player count often shows up several times: in the setup, in a key rule, in a table. Define it once, in the game's frontmatter or in `vault.yaml` (for values many games share), and write `{=name}` where it goes:

```yaml
values:
  main: {2p: 7, 3p: 6, "*": 5}     # by player count: the keys are conditions, "*" for every other case
  vitesse: {+quick: rapide, "*": normale}
  cible: 100                       # a plain value
```

```markdown
Distribuez {=main} cartes à chaque joueur.
! Finissez toujours votre tour avec {=main} cartes en main.
```

- `{=main}` is read as the inline choice it stands for (`{2p: 7 | 3p: 6 | *: 5}`), so everything that works for choices works for values: `tabula show -p 3` writes "6", without a player count every case is shown, and the site's player picker updates it.
- A plain value is written as it is. Value names use letters, digits, `-` and `_`. Quote `"*"` in YAML.
- A game's values win over `vault.yaml`'s, and a translation's over the default-language file's, so a translation only needs to redefine values that contain words.
- Values work in included fragments, with the values of the game that includes them, and in table cells.
- **In a player table**, a choice in a cell (a value or a hand-written one) is shown for its column's player count, so a row can be `| Cartes | {=main} | {=main} | {=main} |`.
- `{=name}` inside a code span is left as it is. A value can't be used inside a choice, and a value's text can't contain `{`, `}` or `|`.
- `tabula check` reports an unknown name (with a "did you mean"), and keys that aren't conditions.

## 9. Section roles

Headings are written in the game's language, so tools can't rely on their text. A **role** tells tools what a section contains. Write it as `#name` in the heading's braces:

```markdown
# Matériel {#components}
# Mise en place {#setup}
# Glossaire {#glossary}
## Cartes Puissance {+supercharge #cards}     ← a role and a condition together
```

Suggested roles: `components`, `goal`, `setup`, `play`, `turn`, `scoring`, `end`, `glossary`, `cards`, `events`, `variants`, `notes`, `faq`. You can use your own names too (`tabula check` only warns about one that looks like a misspelt suggested role, like `#cartes` for `#cards`). Roles are optional and a section can have several (`{#glossary #cards}`).

Tools use roles to show part of a game. `tabula show frantic -s glossary` shows only the glossary, and `-s components -s setup` shows two sections. Filters still apply. `-s` also accepts a heading's title (`-s "fin de la partie"`), so it works on games without roles too. Later, roles will let tools build cheat sheets, card catalogs and a web view with a table of contents.

**Turn summary:** give the section that describes a turn the role `turn` (`## À votre tour {#turn}`). `tabula show GAME --turn` then shows a summary to keep at hand during the game: that section (with its sub-sections), then the key rules and key sections found anywhere else. `tabula export GAME --turn --paper a5` makes a page to print, and `tabula site` adds a "Résumé du tour" page to games that have one.

## 9.1 Card catalog

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
- **A card's picture** is the field `image::`, a path in the game's folder (`image:: media/cartes/phare.png`) or a web address. It isn't listed with the other fields: the site, the HTML export and the book draw it on the card (and as a thumbnail in the catalog table), the terminal writes `[picture: …]`, and editors show it when hovering a reference to the card. `tabula check` reports pictures that are missing.
- **Totals:** a field left empty (`avec::` with no value) in a definition that lists other cards is filled in from them. Numbers are added up; other values are listed once each, with commas:

  ```markdown
  Attaque
  : avec::
    sans::
    Toutes les cartes de type Attaque
    - [[Attaque 2x]]
    - [[Attaque Ciblée 2x]]
    - {+barking} [[Attaque Personnelle 3x]]
  ```

  Each list item counts the first card it refers to. Only the items and cards that apply count: `{+barking}` on the item, or on the card's definition or its section, adds it only with that extension, so `show`, `lookup` and the exports give the total for the current selection, and the interactive page updates it when extensions are ticked. A listed card can be a group itself. A card the list names but doesn't define, or that doesn't have the field, adds nothing. In `tabula cards` and the catalog table, a group is marked Σ and the cards it adds up are listed under it, indented (a card in several groups goes under the first; with `--sort`, groups come last). It isn't counted as a card, and `cards --json` gives it `"kind": "group"` and its `"cards"`.
- `tabula check` warns about empty fields (unless they are totals), fields written twice, `key::` lines below the text (where they'd be read as text), and a card missing a field that most cards in its group have.

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

## 11. Score sheets `.sheet`

A **score sheet** is a page to print and fill in during a game. It is its own file next to the game: `oh-my-socks/oh-my-socks.sheet`, or several (`frantic/manches.sheet`, `frantic/points.sheet`); for a standalone game, `crazy-eights.sheet` next to `crazy-eights.game`. It is written like a game file: a frontmatter, then Markdown, mostly tables.

```markdown
---
title: Feuille de score
size: a4              # a0 to a6, b4, b5, letter, legal, tabloid, or 210x297 (mm)
orientation: portrait # or landscape
rounds: 10            # how many times a {r} row is repeated (default 10)
---

# Frantic :star:

| Manche | {player} | <  |
|--------|----------|----|
|        | points   | Σ  |
| {r}    |          |    |
| Bonus  | //       |    |
```

- **Players are columns.** A heading cell with `{player}` is repeated once per player, with the `<` columns joined to it (here a "points" and a "Σ" column under each player), and so is every cell below it. `{player}` leaves the heading blank, to write a name in; `Joueur {n}` writes "Joueur 1", "Joueur 2"… There is one column per player for the game's largest player count (from its `players:`), or for `tabula sheet GAME -p 3`.
- **Rows are categories or rounds.** Write one row per category. A row whose first cell contains `{r}` is repeated `rounds` times, with `{r}` replaced by 1, 2, 3…
- **An empty cell** is a box to fill in. **`//`** shades a cell that isn't filled in. **`<`** merges a cell with the one on its left, **`^`** with the one above.
- Tables fill the width and height of the page (`fit: false` keeps rows at their natural height). A first column with row headings is as wide as its text; the other columns share the rest equally. An empty heading row is left out.
- Headings, paragraphs, images, symbols (`:star:`, from the game or `vault.yaml`) and values (`{=main}`) work as in games. `---` starts a new page.
- Other frontmatter keys: `margin` (mm, default 10), `font_size` (points, default 11), `language`.
- `tabula sheet GAME` writes the game's sheets as HTML pages the size of the paper, to print or save as PDF; `tabula site` links them from the game's page. `tabula check` checks them (size, orientation, merges, rows of different lengths, misspelt symbols), and `tabula fmt` aligns their tables.

## 12. Wishlist

Games and extensions you'd like go in `wishlist.yaml`, at the root of the vault:

```yaml
- name: Cascadia
  priority: 1                 # 1 = most wanted
  price: 35 CHF
  link: https://…             # where to buy it
- name: Pandora's Box
  for: frantic                # an extension of a game in the vault (its slug or its title)
  priority: 2
  note: the purple box
- name: "Frantic: all the extensions"      # quotes: the name contains ": "
  for: Frantic
- name: Troublemaker
  for: frantic
  in: "Frantic: all the extensions"        # also in that pack: either the pack, or the single ones
- name: Jeu de tarot          # only a name is fine too (or just "- Jeu de tarot")
```

- **Packs:** `in:` names another wish that contains this one (a box with several extensions). The pack is shown with its parts under it ("or separately:"), and gets the best priority among them. Removing the pack (`tabula wish remove`) removes its parts too.
- A value containing `: ` needs quotes in YAML (`name: "A: B"`); `tabula wish add` adds them.
- `tabula wish` lists it, by priority, games first, then extensions with their game. `tabula wish add "Name" --for frantic --in "Pack" --priority 1 --price "15 CHF" --link …` adds a wish at the end of the file, and `tabula wish remove "Name"` takes one out (when it has arrived), leaving the rest of the file and its comments as they are. `--for GAME` also shows only a game's wishes, and `--json` prints them.
- `tabula site` writes a wishlist page, linked from the index ("Souhaits"), and the page of a game links to the extensions wished for it.
- `tabula check` checks the file: a name for each wish, `for:` naming a game of the vault, `in:` naming another wish, a whole-number priority, links starting with `https://`, and misspelt keys.

## 13. Ideas for later (not part of v1.0)

These came up while designing. They'll be added once real games need them.

- **Printable card sheets:** cards from the catalog laid out at real card size, for sleeving or replacing lost cards.
- **Extension files:** large extensions in their own file next to the game (e.g. `frantic/frantic+pandora.game`) that is merged into the base game when the extension is on.
- **Roles and factions:** rules for asymmetric games, e.g. `{@wizard}` and `--role wizard`.
- **Solo and co-op:** `{1p}` already works. Solo bots or automata may need more structure.
- **Player-count expressions:** text computed from the player count, like "deal {= 2 * n} cards" (values, 8.6, cover the common case).
- **Teaching:** marking sections as `{teach}` to produce a 2-minute teaching version.
- **FAQ, errata and house rules:** sections that are always shown but marked as such, perhaps `{house}`.
- **Collection data:** owned, lent to, missing pieces (a checklist built from the component list).
- **Play log:** date, players, scores, winner, used for statistics and "what haven't we played lately?".
- **Links between games:** `[[game:catan]]`, linking an expansion to its base game.

---

## 14. CLI (informative)

The reference CLI is `tabula`. Point it at a vault with `--vault PATH`, or set `$TABULA_VAULT`, or run it from inside the vault.

| Command | What it does |
|---|---|
| `tabula list [-p N] [-l CODE]` | list games, optionally only those playable with N players |
| `tabula show GAME [-p N] [-v VARIANT…] [-e EXTENSION…] [-a] [-s SECTION…] [-k] [-t] [-l CODE] [--json]` | print a game, by default the base game (no extensions or variants), filtered by player count, extensions, variants and language. `-a`/`--all` shows every extension and variant with badges. `-s` shows only some sections (role or title). `-k`/`--key` shows only the key rules and key sections (a cheat sheet), `-t`/`--turn` the turn summary (see 9). `--json` prints the parsed structure. |
| `tabula cards GAME [-p N] [-e …] [-v …] [-a] [-l CODE] [--sort COLUMN] [--json]` | the card catalog (section 9.1): one row per card, counts from the component list for the current selection, and fields as columns |
| `tabula lookup GAME [TERM] [-p N] [-e …] [-v …] [-a] [-l CODE] [--json]` | show one glossary term or component, for use at the table. Case, accents, plurals and small typos are ignored, and partial names work. Filters apply inside the definition. A term from an extension that isn't turned on is still shown, marked "only with +name". The output ends with "see also" for the terms it refers to. When no term has the exact name, it also looks for a section by role or title (`tabula lookup frantic components`). Without a term, lists every term. |
| `tabula export GAME [-p N] [-e …] [-v …] [-a] [-s SECTION…] [-k] [-t] [--paper SIZE] [-i] [-l CODE] [--stdin] [-o FILE]` | write a self-contained HTML page with the same filtering as `show`: table of contents from the headings, glossary entries as cards, `[[references]]` as links with the definition as a tooltip, extension content highlighted, images embedded. Works offline, prints cleanly, and has a dark mode. The default file name describes the selection, e.g. `frantic-4p-supercharge.html`. `-k` exports the cheat sheet (`hearts-4p-key.html`), `-t` the turn summary (`hearts-turn.html`); `--paper a5` (a4, a5, a6, letter) prints on that paper size. `--lines` marks each block with its line in the file (`data-line`, for editors). `-i` makes the page `tabula site` would: everything, with the player and option filters. A translation (`hearts.fr.game`) is exported in its language unless `-l` says otherwise. `--stdin` reads the game's text from standard input instead of the file (an editor's unsaved text; the path still says which game it is). |
| `tabula site [-o FOLDER]` | write the whole vault as a small website (default folder: `site/`): an `index.html` listing every game, with filters for player count, duration and tags and a search, and for each game a page per language (`index.html`, `index.fr.html`) with every extension and variant marked, plus a cheat sheet (`key.html`) when it has key rules. On a game page, a bar lets the reader choose the player count and the extensions and variants (or everything): the page shows only what applies, like `tabula show`, picks the right text in inline choices, renumbers steps and updates card counts. The choice is kept in the address (`#p=4&o=pandora`), so a link opens the same view. Works offline from the folder, or on any static host. The folder is replaced on every run, but only if `tabula site` made it. |
| `tabula book [GAME…] [-p N] [-e …] [-v …] [-k] [-l CODE] [-t TITLE] [-o FILE]` | write games as an EPUB 3 book (default: the whole vault, in `<vault-name>.epub`): a title page and a chapter per game (cover, facts, rules, glossary, card catalogs), with a table of contents of the games and their sections. Without `-e`/`-v` everything is included and marked; with them, only those extensions and variants. `-p` leaves out the games that aren't for that many players. `-k`: only the key rules. Images from the web can't be shown in a book, so their caption stays; links to games that aren't in the book become plain text. |
| `tabula new SLUG [-t TITLE] [-p N] [-l CODE]` / `tabula new bgg ID [SLUG]` | start a game file: `<slug>/<slug>.game` with the frontmatter and the usual sections (with roles, headings in the game's language, a TODO in each). `new bgg ID` fills the frontmatter from BoardGameGeek (title, players, duration, age, year, designers, artists, publisher, box image saved as `media/cover.*`, found without a `cover:` line); `new bgg NAME` lists matching games and their IDs. Needs a BoardGameGeek token in `BGG_TOKEN`. Never replaces an existing game without `--force`. |
| `tabula sheet GAME [NAME] [N] [-p N] [--list] [-o FILE]` | write the game's score sheets (`.sheet`, see 11) as HTML pages the size of the paper, to print or save as PDF: one player column per player (`-p N` or a number, within the game's player count; by default its largest). `NAME` picks one sheet; `--list` lists them; the target can also be a `.sheet` file (`--stdin` for editors) |
| `tabula wish [add\|remove NAME] [--for GAME] [--priority N] [--price …] [--link …] [--note …] [--json]` | the wishlist (`wishlist.yaml`, see 12): list it, add a wish, or remove one |
| `tabula fmt [GAME…] [--check] [--stdin]` | tidy files without changing what they say: one blank line around headings and `---`, no runs of blank lines, aligned table columns (in the table's own `|---|` or `| --- |` style), no trailing spaces, one newline at the end. The frontmatter, code blocks and comments are left as they are, and so are Windows line endings. Every result is parsed again and compared with the original; a file that would read differently is left as it is and reported. Without GAME, every file in the vault (fragments too); with GAME, that game and its translations. `--check`: only list the files that would change (exit 1 if any). `--stdin`: format the one file given from standard input, to standard output (used by editors) |
| `tabula todo [GAME…] [--json]` | list the `<!-- TODO: … -->` and `FIXME` reminders, with file and line, translations included. |
| `tabula check [GAME…] [--strict] [-d] [-s]` | find mistakes: frontmatter, references that match nothing, invalid or never-applying conditions, undeclared variants, missing images, duplicate terms, leftover v0.3 syntax, translation problems. Also checks the shared fragments in `_shared/`, warns about definitions nothing refers to, and counts TODO reminders (they never fail `--strict`). `-d`/`--definitions`: every component must also have a glossary definition. `-s`/`--spell`: also check spelling (see below). `--json`: the issues as JSON, with absolute paths. `--stdin`: check unsaved text for the one file given (used by editors) |

**Spell checking** (`tabula check --spell`, or `check: {spelling: true}` in `vault.yaml` to always do it) looks up every word of the text in a Hunspell dictionary for the file's language, so a translation is checked in its own language. Plain `en` accepts both American and British spellings. It needs the optional `spylls` package (`pipx inject tabula spylls`). The first check in a language downloads its dictionary (the free LibreOffice/Hunspell dictionaries, from the `dictionary-<lang>` packages on npm) into tabula's cache folder (`~/.cache/tabula/dictionaries`, `%LOCALAPPDATA%\tabula\dictionaries` on Windows; `TABULA_CACHE` to change it). Offline, put `<lang>.aff` and `<lang>.dic` there yourself.

- Skipped: the frontmatter, `[[references]]` (but an alias's text is checked), conditions (but the texts of an inline choice are checked), `key::` field names, code, links' addresses, HTML tags, comments, words in capitals and words attached to a number (`1er`, `3x`).
- Accepted: the game's terms and component names, the names in the frontmatter (title, designers, artists, publisher, series, source, location, variants and extensions), the frontmatter's `words:` list, and `words.txt` (or `words.fr.txt` for one language) at the root of the vault, one or more words per line, `#` for comments.
- Unknown words are reported as "spelling", once per line, with a "did you mean" when one of the game's own words is close. Like TODOs, they never count as warnings and never fail `--strict`. Editors show them as information.

Planned: PDF export, `cheatsheet`, `server`.

---

## 15. Cheat sheet

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
values: {main: {2p: 7, "*": 5}}        in frontmatter or vault.yaml; then {=main} in the text
symbols: {gold: media/gold.png}        in frontmatter or vault.yaml; then :gold: in the text
{-pandora} … / {+pandora} …            base rule / extension's replacement
| Joueurs | 3p | 4p |                  player table (or codes in the first column)
extensions: [supercharge]              in frontmatter; then {+supercharge}
! key rule                             cheat-sheet line
## ! Si la tour tombe                  key section (the whole section)
[[#Si la tour tombe]]                  link to a section (by title, or a role: [[#setup]])
![[deck-52#Glossaire]]                 include a shared fragment (_shared/deck-52.game), or one section of it
> [!exemple] Titre                     callout: example, warning (attention), tip (astuce), info (précision)…
<!-- comment -->                       hidden
oh-my-socks.de.game                    translation
oh-my-socks.sheet                      score sheet: | Manche | {player} |, {r} rows, // shaded, < ^ merged
## À votre tour {#turn}                 turn summary (show/export --turn)
Carte                                  a card with fields and a picture
: points:: 3
  image:: media/cards/carte.png
Attaque                                a group: the empty field is the sum of the listed cards' fields
: avec::
  - [[Attaque 2x]]
year: 2019 / series: Micro             in frontmatter: the year it came out / your own key, shown as "Series: Micro"
```

---

## 16. Versions

The spec has a version of its own; the `tabula` CLI and the VS Code extension have theirs (see their changelogs). From 1.0 on, a new feature that doesn't change what existing files mean is a minor version (1.1, 1.2…); a change that makes an existing file mean something else, or no longer valid, is a major version (2.0), and `tabula check` points out what to change, as it does for v0.3 syntax.

**1.0** (October 2026): the format is considered stable. Added since 0.9:

- symbols `:gold:`, in the frontmatter or `vault.yaml` (4);
- callouts `> [!type] Title`, grouped in families, with paragraphs and lists inside (4);
- card pictures `image::` (9.1), and totals: a field left empty in a definition that lists cards is the sum of theirs (9.1);
- the `#turn` role and the turn summary (9);
- extension and variant details: `players`, `duration`, `year`, `needs`, `excludes` (8.5);
- your own frontmatter keys and extension details, shown as "Label: value", and `year` (3.1);
- score sheets `.sheet` (11) and the wishlist `wishlist.yaml`, with packs (12);
- JSON Schemas of the frontmatter, `vault.yaml`, `wishlist.yaml` and `.sheet` files (2.2.1).

**0.9**: values `{=name}` (8.6). **0.4**: Markdown headings, `[[references]]` and `{conditions}`, replacing the v0.3 syntax (`=` headings, `@component`, `[p=…]`).
