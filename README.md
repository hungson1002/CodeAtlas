# CodeAtlas

**A map before the read.**

CodeAtlas is a small, dependency-free codebase atlas for AI coding agents and
the humans who supervise them. Build an index once, then answer the questions
that usually cost a dozen file reads: *where is this symbol, what depends on
it, what breaks if I change it, which tests should I run, and how do I get from
A to B?*

It is a skill (instructions + a CLI) rather than a service. There is no graph
database, no embeddings, no LLM call during build, and no network access.

![CodeAtlas module map](assets/preview.png)

```text
CODEATLAS.md            compact map, commit this (~2–4k tokens)
.code-atlas/index.json  local graph + incremental cache (gitignored)
.code-atlas/diagram.mmd Mermaid dependency graph
.code-atlas/atlas.html  self-contained interactive map (no CDN)
```

## Why

Agents are expensive when they explore by `ls`, `grep`, and whole-file reads.
Most of that context is thrown away. CodeAtlas front-loads the structure into a
cheap artifact and answers follow-up questions with a few hundred tokens:

| Task | Without atlas | With atlas |
|---|---|---|
| Find a symbol | grep + open 3–10 files | `where` → one path:line |
| Scope a change | guess at importers | `impact` → direct/transitive + tests |
| Understand architecture | read READMEs and dirs | `CODEATLAS.md` + diagram |
| Give an agent context | concatenate files | `pack` under a budget |

The index is deterministic and local. Builds are incremental (size + mtime),
and writes are atomic, so an interrupted build cannot corrupt the last good
index.

## Quick start

Requires Python 3.9+ (stdlib only).

```bash
# from a repository
python /path/to/code-atlas/scripts/atlas.py init
python /path/to/code-atlas/scripts/atlas.py map
python /path/to/code-atlas/scripts/atlas.py where Session
python /path/to/code-atlas/scripts/atlas.py impact src/requests/api.py
python /path/to/code-atlas/scripts/atlas.py pack auth --budget 8000
python /path/to/code-atlas/scripts/atlas.py diagram --open
```

On Windows use `python`; on macOS/Linux `python3` works too. Any command accepts
`-C <repo>` so you can query without changing directories.

## Commands

| Command | What it does |
|---|---|
| `init` | Create `.codeatlas.json`, add `.code-atlas/` to `.gitignore`, build |
| `build` | Build the index and outputs; `--full` ignores the cache |
| `update` | Incremental refresh after edits |
| `map` | Print the compact map; `--budget`, `--write` |
| `where <symbol>` | Locate declarations with kind, signature, call counts |
| `impact <target>` | Reverse dependencies, risk score, incoming calls, tests |
| `path <a> <b>` | Shortest dependency path between files or symbols |
| `pack <focus>` | Related files under a token budget |
| `diagram` | Write Mermaid + interactive HTML; `--files`, `--top` |
| `doctor` | Check freshness, coverage, parse errors; `--fix` rebuilds |
| `stats` | Files, LOC, symbols, edges, languages, test command |

Targets can be a file (`src/api.py`), a symbol (`AuthService.login`), or a
directory/module (`src/requests`). Add `--json` for machine-readable output.

## What the map contains

- Entrypoints with reasons (conventional name, package API surface, nothing
  imports it).
- Modules with file/LOC counts, dependency weights, and key exported symbols.
- Hot files ranked by PageRank over the import graph.
- Test count and a detected test command (`pytest`, `npm test`, `go test`,
  `cargo test`, etc.).
- Query recipes so a fresh agent knows what to run next.

The interactive HTML map has two views:

- **Modules** — architecture at a glance, sized by LOC and colored by language.
- **Files** — top files by PageRank, with import arrows, search, pan/zoom, and
  a click-through inspector for symbols and dependencies.

Open `.code-atlas/atlas.html` directly in a browser. Start in file view with
`atlas.html#files`. Everything is embedded in one file; there is no CDN or
server requirement.

## Benchmarks

Measured on a Windows laptop, Python 3.14, cold build (`--full`):

| Repository | Files | LOC | Symbols | Edges | Build |
|---|---:|---:|---:|---:|---:|
| `psf/requests` | 73 | 17.8k | 687 | 1,051 | ~1.0 s |
| `expressjs/express` | 149 | 26.6k | 213 | 389 | ~0.45 s |
| CodeAtlas skill | 11 | 4.2k | 81 | 116 | ~0.16 s |

Incremental `update` reuses unchanged files and is typically much faster. The
map for `requests` fits in roughly 1–2k tokens at the default budget.

## Install as a skill

The repository is the skill: `SKILL.md` at the root, engine in `scripts/`.

```powershell
# Windows — installs to OpenCode, Claude Code, Codex, Cursor, and ~/.agents
.\scripts\install.ps1 -Force
```

```bash
# macOS / Linux
./scripts/install.sh --force
```

Default targets:

| Agent | Path |
|---|---|
| OpenCode (global) | `~/.config/opencode/skills/code-atlas` |
| Claude Code | `~/.claude/skills/code-atlas` |
| Codex CLI | `~/.codex/skills/code-atlas` |
| Cursor | `~/.cursor/skills/code-atlas` |
| Universal | `~/.agents/skills/code-atlas` |

Project-scoped alternatives are `.opencode/skills/`, `.claude/skills/`,
`.cursor/skills/`, and `.agents/skills/`. Agents that only read project
instructions can use the `AGENTS.md` snippet in
`references/agent-setup.md`.

## Configuration

`.codeatlas.json` (all keys optional):

```json
{
  "exclude": ["generated", "fixtures/large"],
  "max_file_kb": 512,
  "module_depth": 2,
  "budget": 3500,
  "entrypoints": ["cmd/server/main.go"],
  "git_churn": true,
  "map_file": "CODEATLAS.md"
}
```

Excludes are additive to built-in defaults and `.gitignore`. Secrets, binaries,
lockfiles, and common build/vendor directories are skipped by default.
`git_churn` counts recent commits per file and feeds the impact risk score.

## Design

Three layers, deliberately small:

- **L0 — Map:** `CODEATLAS.md`, cheap enough to read at the start of every task.
- **L1 — Graph:** local JSON index queried by `where`, `impact`, `path`, `pack`.
- **L2 — Visual:** Mermaid and a self-contained HTML force graph.

No graph DB, no embeddings, no build-time LLM, no mandatory external tools. The
design borrows the useful parts of existing projects — incremental indexing and
blast radius from code-review-graph, deterministic ranked output from ripwire,
a commit-friendly map from stacklit, docs/config nodes from Graphify, and
budgeted packing from repomix — without making any of them dependencies. See
`references/design-notes.md` for the full rationale and non-goals.

## Supported languages

| Tier | Languages |
|---|---|
| Best (AST) | Python |
| Good (regex + heuristics) | TypeScript, JavaScript |
| Basic (regex) | Go, Rust, Java, Kotlin, C#, Ruby, PHP, Swift, Scala, Lua, C, C++, Objective-C, shell |
| Nodes only | Markdown, JSON, YAML, TOML, INI, SQL |

Call graphs are best-effort. Dynamic imports, reflection, dependency injection,
and macro-generated code may be missed. CodeAtlas is for orientation and impact
scoping; use an LSP or semantic tool for precise rename/reference operations.

## Development

```bash
python -m py_compile scripts/atlas.py
python -m unittest discover -s tests -v
```

The test suite builds temporary fixtures and exercises the CLI end to end:
indexing, secret exclusion, relative imports, TS class methods, `where`,
`impact`, `path`, `pack`, `diagram`, and stale → update → fresh recovery.

## License

MIT. See `LICENSE`.
