# CodeAtlas

> `CodeAtlas` · 11 files · 4.2k LOC · 81 symbols
> Generated 2026-10-30 10:07:06 · commit `n/a` · CodeAtlas v0.1.0
> Languages: markdown 5 · config 2 · python 2 · shell 2
> Refresh: `python scripts/atlas.py update` · Query: `python scripts/atlas.py where <symbol>`

## Start here

| File | Why |
|---|---|
| `scripts/atlas.py` | configured entrypoint, public surface, nothing imports it |

## Modules

| Module | Files | LOC | Depends on | Key symbols |
|---|---:|---:|---|---|
| `scripts` | 3 | 2.8k | — | main, build_index, cmd_doctor |
| `references` | 3 | 539 | — | — |
| `.` | 4 | 467 | — | — |
| `tests` | 1 | 374 | — | write, AtlasCLITest |

## Hot files

| File | LOC | Importers |
|---|---:|---:|
| `scripts/atlas.py` | 2.5k | 0 |
| `tests/test_atlas.py` | 374 | 0 |
| `scripts/install.ps1` | 157 | 0 |
| `scripts/install.sh` | 152 | 0 |
| `SKILL.md` | 254 | 0 |
| `README.md` | 200 | 0 |
| `references/design-notes.md` | 188 | 0 |
| `references/query-cookbook.md` | 185 | 0 |

## Tests

- 1 test files · suggested command: `pytest`

## Query recipes

- Find a symbol: `atlas where <name>`
- What breaks: `atlas impact <file|symbol>`
- How A reaches B: `atlas path <fileA> <fileB>`
- Related files under a budget: `atlas pack <area> --budget 8000`
- Visual map: open `.code-atlas/atlas.html`

_~328 tokens · index: `.code-atlas/index.json`_
