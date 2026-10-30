# Query cookbook

Recipes for the questions agents actually ask. `atlas` below means
`python "<skill-dir>/scripts/atlas.py"`; add `-C <repo>` to run against another
checkout.

## 0. First contact with a repo

```bash
atlas doctor                 # is there a fresh index?
atlas build                  # only if missing or stale
atlas map                    # read this, not the directory tree
```

Then pick the one entrypoint that matches the task. Do not read every module
listed in the map.

## 1. "Where is X?"

```bash
atlas where AuthService
atlas where login --limit 10
atlas where send --kind function
atlas where send --json
```

Read the `path:line` and signature. Open that file around the reported line if
the signature is not enough.

- No match? Try the shorter name (`send` instead of `Session.send`).
- Still no match? It may be dynamic, generated, or in an excluded file:
  `rg -n "X"` is the correct fallback.
- `*` marks exported symbols; caller/callee counts hint at importance.

## 2. "What depends on this?"

```bash
atlas impact src/requests/api.py
atlas impact AuthService.login
atlas impact src/requests --depth 3
```

Read:

1. **Risk** — LOW/MEDIUM/HIGH heuristic (importers, transitive files, incoming
   calls, exported symbols, churn).
2. **Direct importers** — the files most likely to break at import time.
3. **Transitive** — the wider radius, with depth.
4. **Incoming calls** — symbols that call into the target.
5. **Tests to run** — start here after editing.

Risk is a prioritization aid, not a guarantee. One direct importer in a public
API can matter more than twenty in tests.

## 3. "Which tests should I run?"

`atlas impact <target>` already reports tests, walking one level further than
the risk radius because tests often import a package entrypoint that re-exports
the target. If the list is empty:

```bash
atlas pack <target> --include-tests --budget 12000
atlas stats                  # suggested test command
```

Fall back to the repository's documented test command. The atlas detects common
runners but does not execute them.

## 4. "How does A reach B?"

```bash
atlas path src/requests/api.py src/requests/models.py
atlas path app/main.py utils/security.py --max-depth 12
```

It searches imports forward first, then reverse (`is imported by`). Symbols are
resolved to their files. Module endpoints are ambiguous and are rejected; use a
file or symbol.

## 5. "Give me the files around X, under a budget"

```bash
atlas pack auth --budget 8000
atlas pack src/requests --budget 12000 --depth 2
atlas pack AuthService.login --budget 4000
```

`pack` starts from the focus set, follows imports up to `--depth`, sorts the
rest by PageRank, and stops at the token budget. Tests are excluded unless they
are the focus or `--include-tests` is set. Use it instead of concatenating
whole directories.

## 6. "Explain the architecture"

```bash
atlas map --budget 2000
atlas diagram                # module view
atlas diagram --files --top 80
open .code-atlas/atlas.html  # or start with atlas.html#files
```

For a human-facing explanation, combine the map's module table with the Mermaid
graph. For a visual review, open the HTML map; node size is LOC, color is the
dominant language, arrows point to imports.

## 7. "I need to make a change safely"

```bash
atlas where <symbol>                 # 1. exact location
atlas impact <symbol>                # 2. importers, callers, tests
atlas pack <symbol> --budget 10000   # 3. only the relevant code
# edit
atlas update                         # 4. refresh the map
atlas doctor                         # 5. confirm FRESH
# run focused tests from step 2, then the subsystem suite
```

Do not skip step 5 after adding/removing files; `doctor` catches new and missing
files that a mtime-only refresh might miss.

## 8. JSON and chaining

```bash
atlas where login --json
atlas impact src/api.py --json
atlas path a.py b.py --json
atlas stats --json
```

Example: find a symbol, then pack its file.

```bash
python - <<'PY'
import json, subprocess, sys
atlas = ["python", r"C:\path\to\code-atlas\scripts\atlas.py"]
result = json.loads(subprocess.check_output(atlas + ["where", "login", "--json"]))
file = result["matches"][0]["file"]
subprocess.run(atlas + ["pack", file, "--budget", "6000"])
PY
```

## 9. Monorepos

```bash
atlas build -C .
atlas pack packages/billing --budget 10000
atlas impact packages/billing/src/invoice.ts
```

If one package has a very different tree, add a nested `.codeatlas.json` and run
from that package directory. One index per root; do not share an index across
branches.

## 10. Stale or wrong results

```bash
atlas doctor
atlas doctor --fix
atlas build --full
atlas stats                  # parse error samples
```

Common causes:

- edited files after the last build → `update`;
- branch checkout with a different HEAD → `update` or `build --full`;
- generated code excluded by config → adjust `exclude`;
- syntax errors → `stats` lists samples; fix or exclude the file;
- dynamic calls → no static edge; use `rg` or an LSP.

## 11. Query budget cheatsheet

| Need | Command | Budget |
|---|---|---|
| Orientation | `map --budget 1500` | small |
| Symbol lookup | `where X` | tiny |
| Change scope | `impact X` | small |
| Context for edit | `pack X --budget 6000` | medium |
| Architecture | `diagram` + map | file output |
| Health | `doctor` | tiny |

If an answer needs more than ~12k tokens of code, narrow the focus before
packing. Bigger packs are not better context; they are more chances to miss the
relevant lines.
