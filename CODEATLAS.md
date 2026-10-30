# CodeAtlas

> `CodeAtlas` · 13 files · 4.6k LOC · 85 symbols
> Generated 2026-10-30 10:37:08 · commit `04aa1ec` · CodeAtlas v1.0.0
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
| `references` | 3 | 599 | — | — |
| `.` | 5 | 588 | — | — |
| `tests` | 2 | 586 | — | write, AtlasCLITest |

## Hot files

| File | LOC | Importers |
|---|---:|---:|
| `scripts/atlas.py` | 2.5k | 0 |
| `tests/test_atlas.py` | 385 | 0 |
| `tests/test_cli.cjs` | 201 | 0 |
| `scripts/install.ps1` | 157 | 0 |
| `scripts/install.sh` | 152 | 0 |
| `README.md` | 263 | 0 |
| `SKILL.md` | 254 | 0 |
| `references/agent-setup.md` | 226 | 0 |

## Tests

- 2 test files · suggested command: `node --test tests/test_cli.cjs && python -m unittest discover -s tests -v`

## Query recipes

- Find a symbol: `atlas where <name>`
- What breaks: `atlas impact <file|symbol>`
- How A reaches B: `atlas path <fileA> <fileB>`
- Related files under a budget: `atlas pack <area> --budget 8000`
- Visual map: open `.code-atlas/atlas.html`

_~347 tokens · index: `.code-atlas/index.json`_
