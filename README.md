# Tabula

Board, card and homemade games as plain Markdown files (`.game`). The rules can be filtered by player count, variant and language. See `SPEC.md` for the format (v0.5).

## Install

```sh
pipx install --editable .   # gives you the `tabula` command everywhere
```

## Use

```sh
export TABULA_VAULT=~/games            # or pass --vault, or cd into the vault

tabula list                            # all games (with where they're stored)
tabula list -p 2                       # games playable with 2 players
tabula show oh-my-socks                # everything, conditions shown as [2p] badges
tabula show oh-my-socks -p 2           # only what applies to 2 players
tabula show hearts -p 4 -v omnibus     # ...with a variant on
tabula show frantic -p 4 -e pandora    # ...with an extension
tabula show hearts -l fr               # French version
tabula show hearts --json              # parsed structure
tabula check                           # find mistakes in every game and translation
```

`vault/` has four example games: `oh-my-socks` (fr), `hearts` (en + fr, with a variant), `stone-circle` (homemade, en + fr, team variant, image) and `crazy-eights` (standalone file).
