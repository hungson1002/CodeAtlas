# Agent setup

CodeAtlas is a standard `SKILL.md` skill with a relative `scripts/` folder. The
same directory works in every agent that supports skills; installers only copy
it to the locations each agent scans.

## Install

### One command (skills CLI) — recommended

```bash
npx skills add hungson1002/CodeAtlas -g
```

This uses the open [skills CLI](https://github.com/vercel-labs/skills) to fetch
the public GitHub repository and install it globally. It copies the whole
repository root, so `scripts/atlas.py` and `references/` arrive with `SKILL.md`.
Omit `-g` to install into the current repository instead.

```bash
# non-interactive, selected agents
npx skills add hungson1002/CodeAtlas -g -y -a claude-code -a codex -a opencode -a cursor
# copy instead of symlink
npx skills add hungson1002/CodeAtlas -g --copy
# inspect first
npx skills add hungson1002/CodeAtlas --list
```

The skills CLI requires Node 22.20+. The installed skill needs Python 3.9+.

### CodeAtlas installer

```bash
npx github:hungson1002/CodeAtlas install

# or keep the CLI around
npm i -g github:hungson1002/CodeAtlas
code-atlas install
```

This installer works on Node 18+, installs all five default destinations in one
go, and does not rely on npm lifecycle scripts. Use `code-atlas status` or
`code-atlas uninstall` for lifecycle management.

Default destinations:

| Agent | Global path | Project path |
|---|---|---|
| OpenCode | `~/.config/opencode/skills/code-atlas` | `.opencode/skills/code-atlas` |
| Claude Code | `~/.claude/skills/code-atlas` | `.claude/skills/code-atlas` |
| Codex CLI | `~/.codex/skills/code-atlas` (`$CODEX_HOME/skills`) | — |
| Cursor | `~/.cursor/skills/code-atlas` | `.cursor/skills/code-atlas` |
| Universal | `~/.agents/skills/code-atlas` | `.agents/skills/code-atlas` |

OpenCode, Cursor, and some other tools also discover `.claude/skills` and
`.agents/skills`, so one of those may be enough. The installer writes all five
by default because copies are cheap and path support differs by version.

After installing, restart the agent (or reload the window) so it re-scans skill
directories. Then ask something like *"use code-atlas to find AuthService"*; the
description is written to trigger on exploration, symbol lookup, impact, tests,
context packing, and diagrams.

### Manual install

Copy this folder so the result is:

```text
<skills-dir>/code-atlas/
  SKILL.md
  scripts/atlas.py
  references/
  README.md
```

Do not copy `.code-atlas/`, `CODEATLAS.md`, `tests/`, or `__pycache__/` when
installing from a development checkout; they belong to the source checkout, not
the installed skill. The `skills` CLI copies them harmlessly, but a manual copy
can stay lean.

### Installer options

```powershell
# Windows source checkout
.\scripts\install.ps1 -Force
.\scripts\install.ps1 -Targets "$HOME\.claude\skills" -Force
.\scripts\install.ps1 -Link          # junction/symlink to the canonical copy
```

```bash
# macOS / Linux source checkout
./scripts/install.sh --force
./scripts/install.sh --target ~/.claude/skills --force
./scripts/install.sh --link
```

`-Force` / `--force` replaces an existing `code-atlas` folder. Without it,
existing destinations are skipped. `-Link` / `--link` installs once to
`~/.agents/skills/code-atlas` and links the other destinations to it; use this
only if your agents follow symlinks/junctions (Cursor Cloud and some SSH setups
do not).

The Git/GitHub installer has equivalent flags:

```bash
npx github:hungson1002/CodeAtlas install --agent claude,codex
npx github:hungson1002/CodeAtlas install --project --agent claude
npx github:hungson1002/CodeAtlas install --link --force
```

## Agents without native skills

Add this to the repository's `AGENTS.md` (Codex, OpenCode, Cursor, and many
others read it) or the agent's memory file (`CLAUDE.md`, `GEMINI.md`, etc.):

```markdown
## CodeAtlas — map before reading

When exploring or editing this repo, use CodeAtlas before broad file reads.

- If `CODEATLAS.md` exists, read it first. Otherwise build it:
  `python ~/.agents/skills/code-atlas/scripts/atlas.py build`
- Locate symbols: `... atlas.py where <name>`
- Scope changes: `... atlas.py impact <file|symbol>` (includes tests)
- Pack context: `... atlas.py pack <area> --budget 8000`
- After edits: `... atlas.py update` then `... atlas.py doctor`

Do not dump whole directories or the index into context when an atlas query can
answer the question. Cite `path:line` from query results.
```

Replace the path with the actual install location. If the agent supports
project skills, prefer copying the skill into `.agents/skills/` or
`.claude/skills/` and committing it with the repo so every contributor gets the
same workflow.

## OpenCode

Global: `~/.config/opencode/skills/code-atlas/SKILL.md`.
Project: `.opencode/skills/code-atlas/SKILL.md`.

OpenCode also scans `.claude/skills` and `.agents/skills` (project and global).
The frontmatter needs `name` and `description`; the name must match the folder
and be lowercase kebab-case. `code-atlas` satisfies both.

## Claude Code

Global: `~/.claude/skills/code-atlas/SKILL.md`.
Project: `.claude/skills/code-atlas/SKILL.md`.

Claude Code loads the description at startup and the body when the skill is
used. Keep the description trigger-rich; CodeAtlas already includes exploration,
symbol lookup, blast radius, tests, packing, and diagram triggers.

## Codex CLI

Global: `~/.codex/skills/code-atlas/SKILL.md` (or
`$CODEX_HOME/skills/code-atlas`). Codex also reads `AGENTS.md`; the snippet above
is enough if your build does not expose a skills menu. Use `/skills` to verify
the install, then invoke it by name.

## Cursor

Global: `~/.cursor/skills/code-atlas/SKILL.md`.
Project: `.cursor/skills/code-atlas/SKILL.md`.

Cursor's docs list both `~/.agents/skills/` and `~/.cursor/skills/` for user
skills, but Cloud Agents and remote SSH sessions do not copy unsynced local
skills. For those, commit the skill under `.cursor/skills/` or `.agents/skills/`
in the repository, or install it into the worker image.

## Verification

```bash
# 1. the skill is where the agent looks
npx skills list -g
ls ~/.claude/skills/code-atlas/SKILL.md
ls ~/.agents/skills/code-atlas/scripts/atlas.py

# 2. the engine runs from the installed copy
python ~/.agents/skills/code-atlas/scripts/atlas.py --version

# 3. an end-to-end build in a scratch repo
cd /tmp/atlas-check
python ~/.agents/skills/code-atlas/scripts/atlas.py init
python ~/.agents/skills/code-atlas/scripts/atlas.py where main
```

On Windows, use `$HOME` or `%USERPROFILE%` in PowerShell paths and quote paths
containing spaces.

## Updating

With the skills CLI:

```bash
npx skills update code-atlas -g
# or reinstall from the repository
npx skills add hungson1002/CodeAtlas -g
```

With the CodeAtlas installer:

```bash
npx github:hungson1002/CodeAtlas install --force
# package CLI equivalent
npm i -g github:hungson1002/CodeAtlas && code-atlas install --force
```

From a source checkout, re-run the installer with `-Force` / `--force`. If you
used `-Link`, only the canonical `~/.agents/skills/code-atlas` copy needs
updating. Restart the agent after updating.

## Uninstalling

```bash
npx skills remove code-atlas -g
# or, with the CodeAtlas CLI
code-atlas uninstall
```

The CodeAtlas CLI removes only copies it manages. Add `--unmanaged` to remove
older manual copies too. Project-local installs can also be removed with the
repository change that added them. The target repository's `.code-atlas/` cache
and `CODEATLAS.md` are independent of the skill install; remove them from the
repo if you no longer want the map.
