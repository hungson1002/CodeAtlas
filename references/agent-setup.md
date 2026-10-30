# Agent setup

CodeAtlas is a standard `SKILL.md` skill with a relative `scripts/` folder. The
same directory works in every agent that supports skills; installers only copy
it to the locations each agent scans.

## Install

### Windows

```powershell
.\scripts\install.ps1 -Force
```

### macOS / Linux

```bash
chmod +x scripts/install.sh
./scripts/install.sh --force
```

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
installing; they belong to the source checkout, not the skill.

### Installer options

```powershell
.\scripts\install.ps1 -Targets "$HOME\.claude\skills" -Force
.\scripts\install.ps1 -Link          # junction/symlink to the canonical copy
```

```bash
./scripts/install.sh --target ~/.claude/skills --force
./scripts/install.sh --link
```

`-Force` / `--force` replaces an existing `code-atlas` folder. Without it,
existing destinations are skipped. `-Link` / `--link` installs once to
`~/.agents/skills/code-atlas` and links the other destinations to it; use this
only if your agents follow symlinks/junctions (Cursor Cloud and some SSH setups
do not).

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

Re-run the installer with `-Force` / `--force` after pulling a new CodeAtlas
version, then restart the agent. If you used `-Link`, only the canonical
`~/.agents/skills/code-atlas` copy needs updating.

## Uninstalling

Remove `<skills-dir>/code-atlas` from each destination. Project-local installs
should be removed with the repository change that added them. The target
repository's `.code-atlas/` cache and `CODEATLAS.md` are independent of the
skill install; remove them from the repo if you no longer want the map.
