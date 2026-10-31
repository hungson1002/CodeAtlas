# CodeAtlas

> `CodeAtlas` · 14 files · 5.8k LOC · 127 symbols
> Generated 2026-10-31 09:59:02 · commit `ae9d50c` · CodeAtlas v1.0.1
> Languages: markdown 5 · config 3 · javascript 2 · python 2 · shell 2
> Refresh: `python scripts/atlas.py update` · Query: `python scripts/atlas.py where <symbol>`

## Start here

| File | Why |
|---|---|
| `scripts/atlas.py` | configured entrypoint, public surface, nothing imports it |

## Modules

| Module | Files | LOC | Depends on | Key symbols |
|---|---:|---:|---|---|
| `scripts` | 3 | 2.8k | — | main, build_index, read_text |
| `bin` | 1 | 1.1k | — | — |
| `.` | 5 | 603 | — | — |
| `references` | 3 | 601 | — | — |
| `tests` | 2 | 677 | — | write, AtlasCLITest |

## Hot files

| File | LOC | Importers |
|---|---:|---:|
| `scripts/atlas.py` | 2.5k | 0 |
| `bin/code-atlas.js` | 1.1k | 0 |
| `tests/test_atlas.py` | 476 | 0 |
| `tests/test_cli.cjs` | 201 | 0 |
| `scripts/install.ps1` | 157 | 0 |
| `scripts/install.sh` | 152 | 0 |
| `README.md` | 270 | 0 |
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
