---
name: code-atlas
description: Build a compact, queryable map of a codebase before reading files. Use when exploring an unfamiliar repository, locating a symbol, estimating blast radius, finding affected tests, packing context under a token budget, or generating an architecture map/diagram. Works with any coding agent and needs only Python 3.9+.
---

# CodeAtlas — a map before the read

CodeAtlas turns a repository into a small, local index, then answers the
questions agents actually ask: *where is this symbol, what depends on it, what
breaks if I change it, which tests should run, and how do I get from A to B?*

**Core rule:** read the map before the code. Never dump a directory tree or a
whole repository into context when an atlas query can answer the question.

The skill directory is the folder containing this `SKILL.md`. Resolve
`scripts/atlas.py` against that folder, but run every command from the **target
repository root**, not from the skill folder. A `CODEATLAS.md` or
`.codeatlas.json` inside the skill folder describes CodeAtlas itself; never use
it as the target repository's map. In examples below, `atlas` means:

```bash
python "<skill-dir>/scripts/atlas.py"      # Windows
python3 "<skill-dir>/scripts/atlas.py"     # macOS / Linux
```

## When to use it

Use CodeAtlas when at least one is true:

- The repository is unfamiliar, large, or has more files than you can skim.
- You need to find a symbol, endpoint, class, or entrypoint.
- You are about to edit a shared file and need its blast radius and tests.
- You need to hand another agent a focused context pack.
- You need an architecture summary or a diagram for a human.

Skip it for a single-file script, a throwaway snippet, or when the user has
already pointed at the exact file and line. Do not rebuild an index on every
question; build once, query many times.

## Workflow

### 1. Detect the current state

From the target repository root:

```bash
python "<skill-dir>/scripts/atlas.py" doctor
```

- `FRESH` → go to step 3.
- `STALE` → `update` (incremental, usually fast).
- `NO INDEX` → `build`.

If the repository is huge and you only care about one area, see
`references/query-cookbook.md` for scoping with `--root` and config excludes.

### 2. Build once

```bash
python "<skill-dir>/scripts/atlas.py" build
```

This creates:

| Output | Purpose | Commit? |
|---|---|---|
| `CODEATLAS.md` | compact human/agent map, ~2–4k tokens | yes |
| `.code-atlas/index.json` | local graph + cache | no (gitignored) |
| `.code-atlas/diagram.mmd` | Mermaid module graph | optional |
| `.code-atlas/atlas.html` | self-contained interactive map | optional |

`init` additionally writes `.codeatlas.json` and adds `.code-atlas/` to
`.gitignore`. Use `update` after edits; use `build --full` only when the cache
is suspect or the parser changed.

### 3. Read the map, not the repo

Read `CODEATLAS.md` first (or run `map` to print it). It contains entrypoints,
module structure, dependencies, hot files, test command, and query recipes.
That is usually enough to choose the first file. If the file is missing, build
it; do not fall back to `ls -R`.

### 4. Ask targeted questions

| Question | Command | Typical cost |
|---|---|---|
| Where is symbol X? | `atlas where X` | ~20–200 tokens |
| What breaks if I change X? | `atlas impact X` | ~50–300 tokens |
| What did my working tree affect? | `atlas impact --changed` | ~50–300 tokens |
| Which tests cover X? | `atlas impact X` (Tests section) | included |
| How does A reach B? | `atlas path A B` | ~20–100 tokens |
| Give me the files around X | `atlas pack X --budget 8000` | budgeted |
| Show architecture | `atlas diagram` | file output |
| Is the index current? | `atlas doctor` | ~50 tokens |

Targets may be a file path (`src/api.py`), a symbol (`Session.send`), or a
module/directory (`src/requests`). Use `--json` when you need to parse the
result or chain it into another command.

### 5. Open only what the query returned

Read the reported file and line window, not the whole file when a symbol range
is known. Keep the loop small: **map → where → impact → pack → read → edit**.

### 6. After editing

```bash
python "<skill-dir>/scripts/atlas.py" update
python "<skill-dir>/scripts/atlas.py" impact --changed
python "<skill-dir>/scripts/atlas.py" doctor
```

`impact --changed` scopes the existing index to git's working tree (staged,
unstaged, and untracked files) and reports affected importers plus tests. New
files must be indexed by `update` first; paths outside the index are listed as
skipped. Use `--staged` for only the index, or `--base <rev>` to compare with a
branch.

Run the focused tests reported by `impact` (or `impact --changed`), then the
subsystem suite. Do not claim a change is safe because the index rebuilt; the
index is a map, not a test runner.

## Command reference

```text
atlas init                 create config + .gitignore entry, then build
atlas build [--full]       build/refresh the index and all outputs
atlas update               incremental refresh (preferred after edits)
atlas map [--budget N]     print the compact map
atlas where <symbol>       path:line, kind, signature, callers/callees
atlas impact <target>      reverse deps, risk score, incoming calls, tests
atlas impact --changed     reverse deps + tests for git-changed files
atlas path <a> <b>         shortest dependency path
atlas pack <focus>         related files under a token budget
atlas diagram [--files]    write Mermaid + interactive HTML
atlas doctor [--fix]       freshness, coverage, unresolved imports, parse errors
atlas stats                index statistics
```

Common flags: `-C <root>` target another repository, `--json` machine output,
`--no-color`, `--limit`, `--depth`, `--top`, `--budget`. For
`impact --changed`, add `--staged` to read only the index or `--base <rev>` to
compare against a branch.

Exit codes: `0` success/fresh, `1` no match or stale index, `2` usage/error.
Treat `where` returning no match as a signal to try `rg -n` for dynamic or
generated symbols, not as proof the symbol does not exist.

## Token discipline

1. **One map read, then queries.** Do not read `CODEATLAS.md` and also list
   every directory.
2. **Prefer `where` over search.** It returns signatures and call counts
   without opening files.
3. **Use `impact` before touching shared code.** The risk score is a heuristic,
   but the direct/transitive lists and tests are concrete.
4. **Use `pack` instead of concatenating files.** It respects a hard token
   budget and orders by relevance/PageRank.
5. **Cap reads.** If a file is longer than ~400 lines, read the symbol range
   first, then expand only if needed.
6. **Use `--json` for chaining**, plain output for humans.
7. **Do not paste the index.** `.code-atlas/index.json` is a cache, not
   context. Never send it to a model wholesale.

## Answer contract

When reporting atlas results to the user or another agent, include:

- `path:line` for every symbol you cite;
- symbol kind and signature;
- risk level plus direct importers when discussing a change;
- the tests that `impact` reported (or explicitly say none were found);
- index freshness if the answer may be stale.

Example:

```text
Session.send — src/requests/sessions.py:753 (method)
Risk: HIGH (12 direct importers, 41 transitive)
Tests: tests/test_requests.py, tests/test_sessions.py
Index: FRESH @ 3c7baaa
```

Do not invent call edges. If the atlas cannot resolve a dynamic call, say so and
fall back to text search or a language server.

## Freshness and safety

- `doctor` compares file size/mtime, tracked file set, and git HEAD. It does not
  hash every file; `build --full` does a clean reparse.
- The index never stores file contents, only metadata, symbols, and edges.
- Secrets (`.env`, keys, credentials), lockfiles, binaries, and common build
  directories are skipped. Review `exclude` before indexing unusual layouts;
  use `include` for a real source directory hidden by a default exclude.
- Writes are atomic (`index.json.tmp` → replace). A failed build does not
  corrupt the previous index.
- Generated outputs are deterministic except for the timestamp and PageRank
  ordering ties; do not fight diffs on `CODEATLAS.md`.

## Languages and fidelity

| Tier | Languages | How |
|---|---|---|
| Best | Python | `ast` — imports, classes, functions, calls, `__all__` |
| Good | TypeScript, JavaScript | regex symbols/imports, class methods, CommonJS exports |
| Basic | Go, Rust, Java, Kotlin, C#, Ruby, PHP, Swift, Scala, Lua, C, C++, Objective-C, shell | regex symbols + imports |

Docs and config files (`md`, `json`, `yaml`, `toml`, `sql`) are indexed as
nodes so documentation and configuration show up in the graph, but they do not
produce call edges.

TypeScript/JavaScript imports follow the project's own config: `tsconfig` or
`jsconfig` `paths`, `baseUrl`, `extends`, and references, plus workspace
packages declared in `package.json` or `pnpm-workspace.yaml`. NodeNext `.js`
specifiers map to their `.ts` source when no emitted file exists. No package
manager is executed during a build.

Known limits: dynamic imports, reflection, dependency injection, decorators
that rewrite functions, generated code, and macros are best-effort. For precise
rename/reference operations, use an LSP or a semantic tool if available;
CodeAtlas is for orientation and impact scoping.

## Configuration

`.codeatlas.json` at the repo root (all keys optional):

```json
{
  "exclude": ["generated", "fixtures/large"],
  "include": ["bin"],
  "max_file_kb": 512,
  "module_depth": 2,
  "budget": 3500,
  "entrypoints": ["cmd/server/main.go"],
  "git_churn": true,
  "map_file": "CODEATLAS.md"
}
```

`.gitignore` patterns are folded in automatically. `include` opts paths back in
when a default exclude or `.gitignore` rule hides them, such as `bin/` or
`third_party/acme`; it does not bypass secret, binary, lockfile, or size checks.
`module_depth` controls how directories are grouped in the map and module graph
(2 = `src/requests`).

## Multi-repo and monorepo notes

- Run one index per repository root. `-C <path>` makes the target explicit.
- For a monorepo, build at the root; use `pack <package-path>` and
  `impact <package-path>` to stay inside one package.
- `tsconfig`/`jsconfig` `paths`, `baseUrl`, `extends`, and project references
  are applied automatically, as are `package.json` workspaces and
  `pnpm-workspace.yaml` packages. Check `doctor` if a new alias stays unresolved.
- If a package has its own tooling and a very large unrelated tree, create a
  nested `.codeatlas.json` and run CodeAtlas from that package directory.
- Do not share one `index.json` between branches. Rebuild after checkout if
  `doctor` reports a different HEAD.

## References

- `references/query-cookbook.md` — question → command recipes and chaining.
- `references/agent-setup.md` — install paths for OpenCode, Claude Code,
  Codex, Cursor, and generic `AGENTS.md` agents.
- `references/design-notes.md` — what CodeAtlas borrows from existing tools,
  what it deliberately omits, and how scoring works.
- `README.md` — human-oriented overview and benchmarks.

## Failure handling

| Symptom | Action |
|---|---|
| `NO INDEX` | `build` |
| `STALE` after checkout | `update`; if parse errors appear, `build --full` |
| symbol not found | try `where` with a shorter name; then `rg -n` |
| wrong/ambiguous edges | inspect `impact`; rely on direct importers, not just risk |
| unresolved imports | `doctor` lists relative imports that resolve to no indexed file; check `tsconfig` `paths`/`baseUrl`, workspace package names, and excludes |
| parse errors | fix syntax or exclude generated files; `stats` shows samples |
| HTML blank | open via a local server or `file://` with `#files`; check browser console |
| huge repo / slow scan | add excludes, lower `max_file_kb`, scope with `-C` |

When in doubt: **map first, query second, read third, edit last.**
