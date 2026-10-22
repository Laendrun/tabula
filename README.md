# Tabula

Board, card and homemade games as plain Markdown files (`.game`). The rules can be filtered by player count, variant and language. See `spec/SPEC.md` for the format (v1.0), and `spec/schemas/` for JSON Schemas of the frontmatter, `vault.yaml`, `wishlist.yaml` and `.sheet` files.

## Install

```sh
pipx install --editable ./cli   # gives you the `tabula` command everywhere
```

## Use

```sh
export TABULA_VAULT=~/games            # or pass --vault, or cd into the vault

tabula new skyjo                       # start a game: skyjo/skyjo.game with the usual sections
tabula new bgg 13                      # ...with the frontmatter filled from BoardGameGeek (needs BGG_TOKEN)
                                       #    covers: media/cover.jpg (or <slug>_cover.jpg) is found by its name
tabula new bgg "ticket to ride"        # find a game's BoardGameGeek ID
tabula list                            # all games (with where they're stored)
tabula list -p 2                       # games playable with 2 players
tabula show oh-my-socks                # base game; player-count rules shown as [2p] badges
tabula show oh-my-socks -p 2           # only what applies to 2 players
tabula show hearts -p 4 -v omnibus     # ...with a variant on
tabula show frantic -p 4 -e pandora    # ...with an extension
tabula show frantic --all              # every extension and variant, with badges
tabula show hearts -l fr               # French version
tabula show frantic -s glossary        # only one section (role or title)
tabula show hearts --key -p 4          # cheat sheet: only the key rules and key sections
tabula show hearts --turn               # turn summary: the {#turn} section, then the key rules
tabula export hearts --turn --paper a5  # ...as a page to print on A5
tabula show hearts --json              # parsed structure
tabula lookup frantic black hole       # one card/term, for use at the table (typos and accents ok)
tabula export frantic -p 4 -e supercharge   # → frantic-4p-supercharge.html (open in a browser, print)
tabula cards frantic -e supercharge --sort points   # card catalog: counts and fields
tabula lookup frantic                  # list every term
tabula site                            # the whole vault as a website in ./site (open site/index.html)
tabula book                            # the whole vault as an EPUB book (e-readers, phones, tablets)
tabula book frantic -p 4 -e pandora    # one game, for one setup
tabula check                           # find mistakes in every game and translation
tabula todo                            # the <!-- TODO: … --> reminders left in game files
tabula sheet frantic -p 4              # the score sheet (frantic/frantic.sheet) for 4 players, to print
tabula wish                            # the wishlist (wishlist.yaml); tabula wish add "Cascadia" --priority 1
tabula fmt                             # tidy every file: blank lines, aligned tables, spaces (never changes the rules)
tabula check -d                        # ...and require a glossary definition for every component
tabula check --spell                   # ...and check spelling, in each file's language (see below)
```

Boxes for examples, warnings and tips: `> [!exemple] Un tour à trois` (or `[!attention]`, `[!astuce]`, `[!précision]`…), drawn in their own color on the site and in the book.

Symbols too: `symbols: {gold: media/gold.png, star: ⭐}` in `vault.yaml` (shared by every game) or in a game, then `:gold:` in the text, drawn as an icon on the site and in the book.

Numbers that depend on the player count can be written once: `values: {main: {2p: 7, "*": 5}}` in the frontmatter (or in `vault.yaml` for every game), then `{=main}` in the text. See the spec, section 8.6.

The frontmatter can hold your own keys too (`series: Rulefactory`, `bought_at: Spiel 2019`): only the keys of the spec do something, the others are shown as they are ("Series: Rulefactory") on the game's page and in `tabula show`. The same goes for an extension's details, next to `description`, `players`, `year`, `needs`…

## Card pictures

A card in a catalog can have a picture: `image:: media/cartes/phare.png` among its fields. The site, the HTML export and the book draw it on the card and in the catalog table; VS Code shows it when you hover a reference to the card.

## Wishlist

Games and extensions you'd like go in `wishlist.yaml` at the root of the vault (name, `for:` an extension's game, `in:` a pack that also contains it, `priority`, `price`, `link`, `note`). `tabula wish` lists it, `tabula wish add "Pandora" --for frantic --priority 1` and `tabula wish remove "Pandora"` change it, and `tabula site` writes a wishlist page to share. See the spec, section 12.

## Score sheets

A score sheet is a `.sheet` file next to the game (`frantic/frantic.sheet`): a frontmatter with the paper size and orientation, then tables to fill in. Players are columns (`{player}`, repeated for each player), rows are categories or rounds (`{r}`, repeated `rounds:` times); `//` shades a cell, `<` and `^` merge cells.

```markdown
---
size: a5
orientation: landscape
---

| Manche | {player} |
|--------|----------|
| {r}    |          |
| Total  |          |
```

`tabula sheet frantic` writes it as a page the size of the paper (one column per player for the game's largest player count, or `-p 3`), to print or save as PDF. `tabula site` links it from the game's page. See the spec, section 11.

Games can share parts, like a standard deck: put them once in `_shared/deck-52.game` and write `![[deck-52]]` (or `![[deck-52#Glossaire]]` for one section) in each game. See the spec, section 10.

## Spell checking

`tabula check --spell` underlines the words the dictionary doesn't know, in each file's language. It needs one extra package:

```sh
pipx inject tabula spylls
```

The first check in a language downloads its Hunspell dictionary (a few MB, once). Game terms, component names and the names in the frontmatter are accepted automatically. Add other correct words (place names, designers' names in credits…) to `words.txt` at the root of the vault, one per line, or to `words: [...]` in a game's frontmatter. To check spelling every time (and in VS Code), put this in `vault.yaml`:

```yaml
check:
  spelling: true
```

Unknown words never count as warnings, so `--strict` still passes.

`examples/vault/` has five example games: `maree-haute` (an original game written to show every feature of the format, with a score sheet: fr + en, a shared fragment, conditions, player tables, key rules and sections, section links, a card catalog with fields, variants and an extension, a cover found by its name), `oh-my-socks` (fr), `hearts` (en + fr, with a variant), `stone-circle` (homemade, en + fr, team variant, image) and `crazy-eights` (standalone file). `maree-haute` and `crazy-eights` share the standard deck from `_shared/deck-52.game` (and its English version `deck-52.en.game`).

## Starting a game from BoardGameGeek

`tabula new bgg ID` fills the frontmatter (title, players, duration, age, year, designers, artists, publisher, box image) from BoardGameGeek, and `tabula new bgg "name"` lists the matching games with their IDs. BoardGameGeek requires a free token for this:

1. Register an application at https://boardgamegeek.com/applications (non-commercial).
2. Put its token in the `BGG_TOKEN` environment variable. On Windows: `setx BGG_TOKEN "your-token"`, then open a new terminal. On macOS/Linux: add `export BGG_TOKEN=your-token` to your shell profile.

Keep the token out of your vault, so it never ends up in git. Without internet or a token, `tabula new SLUG` writes the same file with an empty frontmatter to fill in.

## Website

`tabula site` writes the whole vault to a `site/` folder (`-o` for another one):

- `index.html` lists every game, with filters for player count, duration and tags, and a search.
- Each game gets a page per language, plus a cheat sheet of its key rules. A bar at the top lets you choose the player count and the extensions and variants: the page then shows only what applies, like `tabula show -p 4 -e pandora`, and the address keeps your choice so you can share the link.

Open `site/index.html` in a browser; it works offline. You can also put the folder on any static host. The folder is replaced on every run, but only if `tabula site` made it.

## Book

`tabula book` writes the whole vault as one EPUB, for e-readers and for the reading apps of phones and tablets (Apple Books, Google Play Books, Kindle via "Send to Kindle"…): a title page, then a chapter per game in alphabetical order, with its cover, rules and glossary. The reader's table of contents lists every game and its sections, and `[[references]]` link to the glossary.

- `tabula book hearts frantic` puts only those games in the book.
- By default everything is in, extensions and variants marked like on the site. `-p 4`, `-e pandora` and `-v x` make a book for one setup; games that aren't for that many players are left out.
- `--key` makes a cheat-sheet book (only the key rules), `-l en` picks the language, `-t` the title, `-o` the file.

## Editor

`editors/vscode/` is a VS Code extension: highlighting, `tabula check` while you type (squiggles and the Problems panel), a live preview with the filters (Ctrl+K V), quick fixes, rename (F2), formatting (Shift+Alt+F), an outline, and Ctrl+click on `[[references]]`. Install it from the `.vsix` that CI builds (Actions tab → a green run → Artifacts → *vscode-extension*). See [its README](editors/vscode/README.md) for the settings.

`editors/nvim/` is a Neovim plugin: highlighting, completion of references, sections, values, symbols and frontmatter keys, `tabula check` as diagnostics, `K` and `gd` on references, `:TabulaFormat` and `:TabulaPreview`. Install it with lazy.nvim as `{ "Laendrun/tabula", opts = {} }` (the repository's root is the plugin); see [its README](editors/nvim/README.md).

## Changelog

What changed in each version: [cli/CHANGELOG.md](cli/CHANGELOG.md) for `tabula`, [editors/vscode/CHANGELOG.md](editors/vscode/CHANGELOG.md) for the VS Code extension. Add your changes under *Unreleased*; when you bump a version, rename that heading (a test checks that the newest entry matches the version).

## Code layout

`cli/tabula/` is a small Python package. Each module handles one thing:

| Module | |
|---|---|
| `syntax.py` | regular expressions, names (`norm`, `fold`), player ranges, conditions |
| `source.py` | reading a `.game` file (frontmatter, comments), issues |
| `blocks.py` | parsing the body into blocks (headings, lists, tables, definitions…) |
| `filtering.py` | keeping what applies: players, variants, extensions, sections |
| `vault.py` | finding and loading games and translations |
| `terminal.py` | terminal and JSON rendering |
| `show.py`, `lookup.py`, `cards.py`, `check.py`, `export.py`, `site.py` | one command each |
| `fmt.py` | `tabula fmt`: tidying, and the check that the result reads the same |
| `wishlist.py` | the wishlist: `wishlist.yaml`, `tabula wish`, its check and site page |
| `sheet.py` | score sheets: `.sheet` files, their check and `tabula sheet` |
| `spell.py` | spelling for `check --spell`: dictionaries (downloaded once) and the words to skip |
| `fields.py` | your own frontmatter keys and extension details, shown as "Label: value"; `year` |
| `totals.py` | totals: empty fields of a definition filled in from the cards it lists |
| `cli.py` | the command line (`tabula …`) |

Without installing: `python cli/tabula show hearts`.

## Tests

```sh
pip install -e "./cli[test]"
pytest                                 # runs tests/ against tests/fixtures and the example vault
```

`tests/fixtures/vault/kitchen-sink/` is a test game that uses every feature of the format. When you add a feature, add an example of it there and a test in `tests/`.

## License

MIT, see [LICENSE](LICENSE).
