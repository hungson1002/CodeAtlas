# CodeAtlas

> `CodeAtlas` · 13 files · 4.6k LOC · 86 symbols
> Generated 2026-10-31 09:48:56 · commit `9766372` · CodeAtlas v1.0.0
> Languages: markdown 5 · config 3 · python 2 · shell 2 · javascript 1
> Refresh: `python scripts/atlas.py update` · Query: `python scripts/atlas.py where <symbol>`

## Start here

| File | Why |
|---|---|
| `scripts/atlas.py` | configured entrypoint, public surface, nothing imports it |

## Modules

| Module | Files | LOC | Depends on | Key symbols |
|---|---:|---:|---|---|
| `scripts` | 3 | 2.8k | — | main, build_index, cmd_doctor |
| `.` | 5 | 591 | — | — |
| `references` | 3 | 600 | — | — |
| `tests` | 2 | 634 | — | write, AtlasCLITest |

## Hot files

| File | LOC | Importers |
|---|---:|---:|
| `scripts/atlas.py` | 2.5k | 0 |
| `tests/test_atlas.py` | 433 | 0 |
| `tests/test_cli.cjs` | 201 | 0 |
| `scripts/install.ps1` | 157 | 0 |
| `scripts/install.sh` | 152 | 0 |
| `README.md` | 266 | 0 |
| `SKILL.md` | 254 | 0 |
| `references/agent-setup.md` | 227 | 0 |

## Tests

- 2 test files · suggested command: `node --test tests/test_cli.cjs && python -m unittest discover -s tests -v`

## Query recipes

- Find a symbol: `atlas where <name>`
- What breaks: `atlas impact <file|symbol>`
- How A reaches B: `atlas path <fileA> <fileB>`
- Related files under a budget: `atlas pack <area> --budget 8000`
- Visual map: open `.code-atlas/atlas.html`

_~347 tokens · index: `.code-atlas/index.json`_
