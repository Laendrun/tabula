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
tabula show hearts --json              # parsed structure
tabula lookup frantic black hole       # one card/term, for use at the table (typos and accents ok)
tabula export frantic -p 4 -e supercharge   # → frantic-4p-supercharge.html (open in a browser, print)
tabula cards frantic -e supercharge --sort points   # card catalog: counts and fields
tabula lookup frantic                  # list every term
tabula check                           # find mistakes in every game and translation
tabula check -d                        # ...and require a glossary definition for every component
```

`examples/vault/` has four example games: `oh-my-socks` (fr), `hearts` (en + fr, with a variant), `stone-circle` (homemade, en + fr, team variant, image) and `crazy-eights` (standalone file).

## Editor

`editors/vscode/` is a VS Code extension: highlighting, `tabula check` while you type (squiggles and the Problems panel), an outline, and Ctrl+click on `[[references]]`. Download the `.vsix` from the *vscode-extension* artifact of the latest CI run (Actions tab) and install it with `code --install-extension tabula-game-files-<version>.vsix`. See [its README](editors/vscode/README.md) for the settings.

## Tests

```sh
pip install -e "./cli[test]"
pytest                                 # runs tests/ against tests/fixtures and the example vault
```

`tests/fixtures/vault/kitchen-sink/` is a test game that uses every feature of the format. When you add a feature, add an example of it there and a test in `tests/`.
