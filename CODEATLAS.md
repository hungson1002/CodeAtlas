# CodeAtlas

> `CodeAtlas` · 14 files · 6.9k LOC · 129 symbols
> Generated 2026-11-02 09:13:30 · commit `adda58c` · CodeAtlas v1.1.1
> Languages: markdown 5 · config 3 · javascript 2 · python 2 · shell 2
> Refresh: `python scripts/atlas.py update` · Query: `python scripts/atlas.py where <symbol>`

## Start here

| File | Why |
|---|---|
| `scripts/atlas.py` | configured entrypoint, public surface, nothing imports it |

## Modules

| Module | Files | LOC | Depends on | Key symbols |
|---|---:|---:|---|---|
| `scripts` | 3 | 3.8k | — | main, build_index, read_text |
| `bin` | 1 | 1.1k | — | — |
| `.` | 5 | 608 | — | — |
| `references` | 3 | 605 | — | — |
| `tests` | 2 | 713 | — | write, AtlasCLITest |

## Hot files

| File | LOC | Importers |
|---|---:|---:|
| `scripts/atlas.py` | 3.5k | 0 |
| `bin/code-atlas.js` | 1.1k | 0 |
| `tests/test_atlas.py` | 512 | 0 |
| `tests/test_cli.cjs` | 201 | 0 |
| `scripts/install.ps1` | 157 | 0 |
| `scripts/install.sh` | 152 | 0 |
| `README.md` | 275 | 0 |
| `SKILL.md` | 261 | 0 |

## Tests

- 2 test files · suggested command: `node --test tests/test_cli.cjs && python -m unittest discover -s tests -v`

## Query recipes

- Find a symbol: `atlas where <name>`
- What breaks: `atlas impact <file|symbol>`
- How A reaches B: `atlas path <fileA> <fileB>`
- Related files under a budget: `atlas pack <area> --budget 8000`
- Visual map: open `.code-atlas/atlas.html`

_~353 tokens · index: `.code-atlas/index.json`_
