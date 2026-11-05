# Design notes

CodeAtlas is a distillation, not a bundle. This note records what it borrows,
what it deliberately leaves out, and why the implementation looks the way it
does.

## Influences

| Project | Useful idea | What CodeAtlas does |
|---|---|---|
| **stacklit** | One command produces a commit-friendly map | `build` writes `CODEATLAS.md`; the map is the first thing an agent reads |
| **code-review-graph** | Incremental index + blast radius + test selection | size/mtime reuse, reverse dependency walk, risk score, tests section |
| **ripwire** | Deterministic, ranked call graph with byte budgets | sorted output, PageRank, `pack --budget`, stable JSON |
| **repomix** | Pack a repository for an LLM | `pack` follows imports instead of packing everything, and respects a token budget |
| **Graphify** | Include docs, config, and SQL in the graph | non-code files are indexed as nodes; they do not create call edges |
| **Understand-Anything** | Visual, interactive architecture | self-contained HTML force graph with module/file views and an inspector |
| **serena** | LSP-backed semantic operations | not reimplemented; CodeAtlas is the cheap orientation layer before an LSP |
| **DeepWiki / gitdiagram** | Architecture diagrams on demand | Mermaid module graph and an offline HTML map |

The common failure mode of “combine all the tools” is context bloat and
ambiguous instructions. CodeAtlas keeps one entrypoint (`scripts/atlas.py`) and
one query ladder (map → where → impact → pack), so an agent never has to choose
between five engines.

## Layers

```text
L0  CODEATLAS.md            ~2–4k tokens, read at task start
L1  .code-atlas/index.json  graph + cache, queried by the CLI
L2  diagram.mmd / atlas.html visual review for humans
```

L0 is committed. L1 is gitignored and disposable. L2 is generated from L1 and
can be regenerated at any time.

## Data model

The index stores one record per file:

```json
{
  "lang": "python",
  "size": 1234,
  "mtime": 1700000000,
  "sha1": "...",
  "loc": 42,
  "module": "src/api",
  "imports_raw": [{"spec": ".models", "alias": null}],
  "from_imports": [{"spec": ".models", "name": "Request", "alias": "Request"}],
  "symbols": [
    {
      "id": "src/api.py::send",
      "name": "send",
      "qualname": "send",
      "kind": "function",
      "line": 10,
      "end_line": 30,
      "signature": "def send(request):",
      "exported": true,
      "doc": "...",
      "calls": ["Request.prepare", "session.send"]
    }
  ],
  "imports": ["src/models.py"],
  "external": ["requests"],
  "errors": []
}
```

Edges are tuples (`from`, `to`, kind) where kind is `i` (import) or `c` (call).
Symbol ids are `path::qualname`; file ids are paths. This avoids a database and
keeps the file inspectable with any JSON tool.

## Parsing strategy

- **Python** uses `ast`: imports, `ImportFrom` levels, classes, functions,
  methods, `__all__`, docstrings, and call expressions. This is the highest
  fidelity tier.
- **TypeScript / JavaScript** use line-oriented regexes for declarations,
  arrow functions, CommonJS exports, prototype assignments, and class methods
  (tracked with brace depth). Imports come from `import`, `export ... from`,
  `require`, and dynamic `import()`.
- **Other languages** use declaration/import regex tables. Enough for
  orientation, not for semantic refactoring.
- **Comments** are stripped before symbol extraction while preserving line
  numbers; strings are respected so `//` inside a URL does not eat code.

Regex parsing is intentionally conservative. It is better to miss a symbol than
to invent a call edge that sends an agent to the wrong file.

## Import resolution

Resolution is ordered and stops at the first unambiguous hit:

1. Relative specs (`./x`, `../x`, Python `.x` / `..x`).
2. Project aliases: `tsconfig`/`jsconfig` `paths` and `baseUrl` (JSONC,
   `extends`, and references are honoured), then workspace packages declared in
   `package.json` or `pnpm-workspace.yaml` via their `exports`/`main`/`types`.
3. Exact path or path + language extension.
4. Directory index (`index.ts`, `__init__.py`, `mod.rs`).
5. Python dotted module paths, including `src/` layouts.
6. Java/Kotlin/C#/Scala dotted imports, with a unique-class fallback.
7. Unique suffix match (`services.auth` → `app/services/auth.py`).
8. Unique basename match.

NodeNext imports (`./b.js`) fall back to their TypeScript source (`b.ts`) only
after exact candidates fail, so a real emitted `.js` file still wins. Ambiguous
suffix and basename matches are rejected. Bare JS/TS specifiers that do not
match a configured alias or workspace package are treated as npm packages, not
local files: resolving `require('ejs')` to `test/acceptance/ejs.js` would create
a false edge.

Call resolution prefers, in order: same-file symbol, `from X import y` mapping,
module alias (`import * as api`), then a globally unique name. Attribute calls
prefer methods over top-level functions with the same name.

## Ranking

`PageRank` runs over the import graph (20 iterations, damping 0.85). It answers
“which files matter to the rest of the repo?” and drives hot files, the file
view, pack ordering, and entrypoint scoring. It is not a correctness signal.

Entrypoints combine conventional names (`main.py`, `index.ts`, `app.py`),
package API surfaces (`__init__.py` with several imports), files nothing
imports, and PageRank. Examples/demos and tests are penalized. Modules are
ranked with a priority function that down-weights tests, docs, and examples so
the map leads with production code.

The impact risk score is a bounded heuristic:

```text
risk = 6·direct + 2·transitive + 1.2·min(incoming,30)
     + min(exported,20) + 0.8·min(churn,30)
```

It is capped at 100 and mapped to LOW (<30), MEDIUM (<60), HIGH. Treat it as a
triage aid; the lists are the evidence.

## Incremental builds

A file is reused when parser version, size, and integer mtime all match. This is
fast and safe for normal edits; `build --full` exists for suspicious caches and
parser changes. `.gitignore` and config excludes are compiled once per scan
instead of running `fnmatch` for every pattern on every path.

Writes go to `index.json.tmp` and are atomically replaced, so a crash leaves the
previous index intact. `doctor` checks tracked file size/mtime, new/missing
files, and git HEAD; it does not hash every file.

The map keeps the test command compact. A `package.json` test script longer
than 160 characters is rendered as `npm test` (or `pnpm`/`yarn`/`bun test`
based on the lockfile), because generated test lists can otherwise dominate the
map's token budget. `test_command` in `.codeatlas.json` overrides detection.

## Visual map

`atlas.html` embeds the node/link payload and a deterministic canvas layout.
No CDN, no build step, no server. Two views:

- **Modules** — architecture, sized by LOC, colored by dominant language, with
  dotted containment links from the repository root and aggregated import/call
  edges between modules.
- **Files** — code files grouped into module clusters, import arrows (solid),
  cross-file calls (dashed), search, pan/zoom, and an inspector.

`#files` opens the file view directly (a hash works on `file://` URLs; a query
string is less reliable on Windows). Labels are shown for modules and for files
when they fit; selected nodes keep their labels. Layout is computed once from the
index with no animation loop, so repeated captures are stable, and `fitView`
frames the graph after layout.

## Deliberate non-goals

- **No graph database.** A JSON file plus BFS is enough at repository scale;
  Neo4j/Memgraph add setup and failure modes.
- **No embeddings by default.** Privacy, cost, and staleness. The structural
  graph answers “where/what depends” better than vector similarity.
- **No LLM at build time.** Builds must be deterministic, offline, and cheap.
- **No LSP reimplementation.** Precise references/renames belong to serena,
  IDEs, and language servers. CodeAtlas is the layer before them.
- **No mandatory external tools.** Everything works with Python 3.9+ stdlib.
- **No whole-repo packing by default.** `pack` is focus + budget, because a
  repository dump is the problem CodeAtlas exists to avoid.

## Known limits

- Call graphs are static and best-effort; dynamic dispatch, DI, decorators,
  reflection, and macros can hide edges.
- Regex parsers can miss unusual formatting; Python is the reliable tier.
- PageRank and risk favor connected code; a critical leaf utility can look
  unimportant.
- Monorepos with several roots need per-root indexes or nested config. Import
  aliases and workspace packages are resolved from the repository, but each
  root still gets its own `index.json`.
- Generated/vendored code is excluded by default; if it matters, add an
  explicit include or a scoped config.
- The HTML map is for exploration, not for editing; it has no file contents.

## Future adapters

The CLI is intentionally stable so adapters can be added without changing the
skill workflow: an optional `--adapter serena` for precise references, an MCP
wrapper around `where/impact/pack`, or a CI job that fails when `doctor` reports
STALE. None of these are required for the core path.
