# Tabula

Board, card and homemade games as plain Markdown files (`.game`). The rules can be filtered by player count, variant and language. See `spec/SPEC.md` for the format (v0.7).

## Install

```sh
pipx install --editable ./cli   # gives you the `tabula` command everywhere
```

## Use

```sh
export TABULA_VAULT=~/games            # or pass --vault, or cd into the vault

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
tabula show hearts --json              # parsed structure
tabula lookup frantic black hole       # one card/term, for use at the table (typos and accents ok)
tabula export frantic -p 4 -e supercharge   # → frantic-4p-supercharge.html (open in a browser, print)
tabula cards frantic -e supercharge --sort points   # card catalog: counts and fields
tabula lookup frantic                  # list every term
tabula site                            # the whole vault as a website in ./site (open site/index.html)
tabula check                           # find mistakes in every game and translation
tabula todo                            # the <!-- TODO: … --> reminders left in game files
tabula check -d                        # ...and require a glossary definition for every component
```

`examples/vault/` has four example games: `oh-my-socks` (fr), `hearts` (en + fr, with a variant), `stone-circle` (homemade, en + fr, team variant, image) and `crazy-eights` (standalone file).

## Website

`tabula site` writes the whole vault to a `site/` folder (`-o` for another one):

- `index.html` lists every game, with filters for player count, duration and tags, and a search.
- Each game gets a page per language, showing everything with extensions and variants marked, plus a cheat sheet of its key rules.

Open `site/index.html` in a browser; it works offline. You can also put the folder on any static host. The folder is replaced on every run, but only if `tabula site` made it.

## Editor

`editors/vscode/` is a VS Code extension: highlighting, `tabula check` while you type (squiggles and the Problems panel), an outline, and Ctrl+click on `[[references]]`. Install it from the `.vsix` that CI builds (Actions tab → a green run → Artifacts → *vscode-extension*). See [its README](editors/vscode/README.md) for the settings.

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
