#!/usr/bin/env node
'use strict';

/**
 * CodeAtlas CLI.
 *
 * Two jobs:
 *   1. install / inspect / remove the skill for coding agents;
 *   2. forward every engine command (build, where, impact, ...) to atlas.py.
 *
 * The installer intentionally does not use npm lifecycle scripts. npm 11 blocks
 * postinstall by default and many teams disable install scripts, so the skill
 * install is an explicit, inspectable command.
 */

const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const { spawn, spawnSync } = require('node:child_process');
const { parseArgs } = require('node:util');

const PKG_ROOT = path.resolve(__dirname, '..');
const PKG = readJson(path.join(PKG_ROOT, 'package.json')) || { version: '0.0.0' };
const NAME = 'code-atlas';
const MANIFEST = '.codeatlas-skill.json';
const MANIFEST_SCHEMA = 1;
const ATLAS = path.join(PKG_ROOT, 'scripts', 'atlas.py');
const ATLAS_COMMANDS = new Set([
  'init',
  'build',
  'update',
  'map',
  'where',
  'impact',
  'path',
  'pack',
  'diagram',
  'doctor',
  'stats',
]);

const COPY_FILES = [
  'SKILL.md',
  'README.md',
  'LICENSE',
  'scripts/atlas.py',
];
const COPY_DIRS = ['references', 'assets'];
const SKIP_NAMES = new Set(['__pycache__', '.code-atlas', '.DS_Store', 'Thumbs.db']);

let pythonCache;

function readJson(file) {
  try {
    return JSON.parse(fs.readFileSync(file, 'utf8'));
  } catch {
    return null;
  }
}

function getHome() {
  return path.resolve(process.env.CODEATLAS_HOME || os.homedir());
}

function expandHome(value) {
  if (!value) return value;
  if (value === '~') return getHome();
  if (value.startsWith('~/') || value.startsWith('~\\')) {
    return path.join(getHome(), value.slice(2));
  }
  return path.resolve(value);
}

function displayPath(value) {
  const home = getHome();
  const absolute = path.resolve(value);
  if (absolute === home) return '~';
  const prefix = home.endsWith(path.sep) ? home : home + path.sep;
  if (absolute.toLowerCase().startsWith(prefix.toLowerCase())) {
    return '~' + path.sep + absolute.slice(prefix.length);
  }
  return absolute;
}

function canonicalPath(value) {
  try {
    return fs.realpathSync.native(value);
  } catch {
    return path.resolve(value);
  }
}

function samePath(a, b) {
  const left = canonicalPath(a);
  const right = canonicalPath(b);
  return process.platform === 'win32'
    ? left.toLowerCase() === right.toLowerCase()
    : left === right;
}

function agentDefinitions() {
  const home = getHome();
  const configHome = process.env.XDG_CONFIG_HOME
    ? expandHome(process.env.XDG_CONFIG_HOME)
    : path.join(home, '.config');
  const codexHome = process.env.CODEX_HOME
    ? expandHome(process.env.CODEX_HOME)
    : path.join(home, '.codex');

  return [
    {
      id: 'opencode',
      label: 'OpenCode',
      globalParent: path.join(configHome, 'opencode', 'skills'),
      projectParent: path.join('.opencode', 'skills'),
    },
    {
      id: 'claude',
      label: 'Claude Code',
      globalParent: path.join(home, '.claude', 'skills'),
      projectParent: path.join('.claude', 'skills'),
    },
    {
      id: 'codex',
      label: 'Codex CLI',
      globalParent: path.join(codexHome, 'skills'),
      projectParent: null,
    },
    {
      id: 'cursor',
      label: 'Cursor',
      globalParent: path.join(home, '.cursor', 'skills'),
      projectParent: path.join('.cursor', 'skills'),
    },
    {
      id: 'agents',
      label: 'Universal',
      globalParent: path.join(home, '.agents', 'skills'),
      projectParent: path.join('.agents', 'skills'),
    },
  ];
}

function agentById(id) {
  return agentDefinitions().find((agent) => agent.id === id);
}

function parseList(values) {
  const out = [];
  for (const value of values || []) {
    for (const part of String(value).split(',')) {
      const trimmed = part.trim().toLowerCase();
      if (trimmed && !out.includes(trimmed)) out.push(trimmed);
    }
  }
  return out;
}

function selectedAgents(values) {
  const ids = parseList(values.agent);
  if (!ids.length) return agentDefinitions();
  const unknown = ids.filter((id) => !agentById(id));
  if (unknown.length) {
    throw new Error(
      `unknown agent: ${unknown.join(', ')} (choose from ${agentDefinitions()
        .map((agent) => agent.id)
        .join(', ')})`
    );
  }
  return ids.map((id) => agentById(id));
}

function globalTargets(values) {
  return selectedAgents(values).map((agent) => ({
    agent,
    scope: 'global',
    dest: path.join(agent.globalParent, NAME),
  }));
}

function projectTargets(values) {
  const root = values['project-dir']
    ? expandHome(values['project-dir'])
    : process.cwd();
  const requested = parseList(values.agent);
  const agents = requested.length ? selectedAgents(values) : [agentById('agents')];
  const targets = [];
  for (const agent of agents) {
    if (!agent.projectParent) {
      if (requested.length) {
        throw new Error(`${agent.label} has no project-scoped skill path; install it globally`);
      }
      continue;
    }
    targets.push({
      agent,
      scope: 'project',
      dest: path.join(root, agent.projectParent, NAME),
    });
  }
  return targets;
}

function customTargets(values) {
  return (values.target || []).map((parent) => ({
    agent: { id: 'custom', label: 'Custom' },
    scope: 'custom',
    dest: path.join(expandHome(parent), NAME),
  }));
}

function resolveTargets(values) {
  const hasTargets = (values.target || []).length > 0;
  if (values.project && hasTargets) {
    throw new Error('use either --project or --target, not both');
  }
  if (hasTargets) return dedupeTargets(customTargets(values));
  if (values.project) return dedupeTargets(projectTargets(values));
  return dedupeTargets(globalTargets(values));
}

function dedupeTargets(targets) {
  const seen = new Set();
  const out = [];
  for (const target of targets) {
    const key =
      process.platform === 'win32'
        ? path.resolve(target.dest).toLowerCase()
        : path.resolve(target.dest);
    if (seen.has(key)) continue;
    seen.add(key);
    out.push(target);
  }
  return out;
}

function inspectTarget(dest) {
  let stat;
  try {
    stat = fs.lstatSync(dest);
  } catch (error) {
    if (error.code === 'ENOENT') return { state: 'missing', linked: false };
    return { state: 'error', linked: false, error: error.message };
  }

  const linked = stat.isSymbolicLink();
  let realPath = dest;
  if (linked) {
    try {
      realPath = fs.realpathSync.native(dest);
    } catch {
      return { state: 'broken', linked: true };
    }
  }

  const manifest = readJson(path.join(realPath, MANIFEST));
  if (manifest && manifest.name === NAME) {
    const version = String(manifest.version || '?');
    return {
      state: version === PKG.version ? 'current' : 'outdated',
      version,
      linked,
      realPath,
    };
  }

  if (fs.existsSync(path.join(realPath, 'SKILL.md'))) {
    return { state: 'unmanaged', linked, realPath };
  }

  if (!linked && !stat.isDirectory()) {
    return { state: 'invalid', linked, realPath };
  }

  return { state: 'unmanaged', linked, realPath };
}

function removePath(target) {
  let stat;
  try {
    stat = fs.lstatSync(target);
  } catch (error) {
    if (error.code === 'ENOENT') return;
    throw error;
  }
  if (stat.isSymbolicLink()) {
    try {
      fs.unlinkSync(target);
    } catch {
      // Windows junction cleanup fallback.
      fs.rmdirSync(target);
    }
    return;
  }
  fs.rmSync(target, { recursive: true, force: true });
}

function copyPayloadTo(dest) {
  fs.mkdirSync(dest, { recursive: true });
  for (const rel of COPY_FILES) {
    const source = path.join(PKG_ROOT, rel);
    if (!fs.existsSync(source)) {
      throw new Error(`package is missing ${rel}`);
    }
    const target = path.join(dest, rel);
    fs.mkdirSync(path.dirname(target), { recursive: true });
    fs.copyFileSync(source, target);
  }
  for (const rel of COPY_DIRS) {
    const source = path.join(PKG_ROOT, rel);
    if (!fs.existsSync(source)) continue;
    fs.cpSync(source, path.join(dest, rel), {
      recursive: true,
      force: true,
      filter: (entry) => {
        const base = path.basename(entry);
        return !SKIP_NAMES.has(base) && !base.endsWith('.pyc');
      },
    });
  }
  if (!fs.existsSync(path.join(dest, 'scripts', 'atlas.py'))) {
    throw new Error('install incomplete: scripts/atlas.py is missing');
  }
  const manifest = {
    schema: MANIFEST_SCHEMA,
    name: NAME,
    version: PKG.version,
    installedAt: new Date().toISOString(),
    source: PKG_ROOT,
  };
  fs.writeFileSync(path.join(dest, MANIFEST), JSON.stringify(manifest, null, 2) + '\n');
}

function installPayload(dest, options = {}) {
  const force = Boolean(options.force);
  const dryRun = Boolean(options.dryRun);
  const inspection = inspectTarget(dest);

  if (inspection.linked && !force) {
    return {
      action: 'skip',
      inspection,
      note: 'linked; update the canonical copy or use --force',
    };
  }
  if (inspection.state === 'current' && !force) {
    return { action: 'current', inspection };
  }
  if (
    !force &&
    (inspection.state === 'unmanaged' ||
      inspection.state === 'invalid' ||
      inspection.state === 'broken')
  ) {
    return {
      action: 'skip',
      inspection,
      note: 'unmanaged; use --force to replace',
    };
  }

  let action = 'install';
  if (inspection.state === 'current') action = 'reinstall';
  else if (inspection.state === 'outdated') action = 'update';
  else if (inspection.state !== 'missing') action = 'replace';

  if (dryRun) {
    return { action: `would-${action}`, inspection };
  }

  const parent = path.dirname(dest);
  fs.mkdirSync(parent, { recursive: true });
  const tmp = path.join(
    parent,
    `.${NAME}.tmp-${process.pid}-${Date.now().toString(36)}`
  );

  try {
    copyPayloadTo(tmp);
    if (fs.existsSync(dest) || inspection.state !== 'missing') {
      removePath(dest);
    }
    fs.renameSync(tmp, dest);
  } catch (error) {
    try {
      if (fs.existsSync(tmp)) removePath(tmp);
    } catch {
      // Best-effort cleanup; keep the original error.
    }
    throw error;
  }

  return { action, inspection };
}

function linkPayload(dest, canonical, options = {}) {
  const inspection = inspectTarget(dest);
  if (inspection.linked && samePath(inspection.realPath, canonical)) {
    if (inspection.state === 'current') {
      return { action: 'current', inspection, note: 'linked' };
    }
  }
  if (
    !options.force &&
    (inspection.state === 'unmanaged' ||
      inspection.state === 'invalid' ||
      inspection.state === 'broken')
  ) {
    return {
      action: 'skip',
      inspection,
      note: 'unmanaged; use --force to replace',
    };
  }
  if (options.dryRun) {
    return { action: 'would-link', inspection };
  }

  fs.mkdirSync(path.dirname(dest), { recursive: true });
  if (inspection.state !== 'missing') removePath(dest);
  try {
    fs.symlinkSync(
      canonical,
      dest,
      process.platform === 'win32' ? 'junction' : 'dir'
    );
    return { action: 'link', inspection };
  } catch (error) {
    // Junction/symlink can be blocked by policy. A copy still works.
    const copied = installPayload(dest, { force: true });
    return {
      ...copied,
      action: copied.action === 'current' ? 'copied' : copied.action,
      note: `link failed (${error.code || 'error'}); copied instead`,
    };
  }
}

function installOne(target, options = {}) {
  const inspection = inspectTarget(target.dest);
  if (inspection.linked && inspection.state === 'outdated' && !options.force) {
    const updated = installPayload(inspection.realPath, {
      force: false,
      dryRun: options.dryRun,
    });
    return {
      ...updated,
      action: updated.action === 'update' ? 'update-linked' : updated.action,
      targetInspection: inspection,
    };
  }
  return installPayload(target.dest, options);
}

function pythonCandidates() {
  const candidates = [];
  if (process.env.CODEATLAS_PYTHON) {
    candidates.push({ command: process.env.CODEATLAS_PYTHON, args: [] });
  }
  if (process.platform === 'win32') {
    candidates.push({ command: 'python', args: [] });
    candidates.push({ command: 'py', args: ['-3'] });
    candidates.push({ command: 'python3', args: [] });
  } else {
    candidates.push({ command: 'python3', args: [] });
    candidates.push({ command: 'python', args: [] });
  }
  return candidates;
}

function findPython() {
  if (pythonCache !== undefined) return pythonCache;

  const probe =
    'import json,sys;print(json.dumps({"version":"%d.%d.%d"%sys.version_info[:3],"executable":sys.executable}))';

  for (const candidate of pythonCandidates()) {
    const result = spawnSync(
      candidate.command,
      [...candidate.args, '-c', probe],
      {
        encoding: 'utf8',
        timeout: 5000,
        windowsHide: true,
        env: { ...process.env, PYTHONIOENCODING: 'utf-8' },
      }
    );
    if (result.status !== 0 || !result.stdout) continue;

    const lines = result.stdout
      .split(/\r?\n/)
      .map((line) => line.trim())
      .filter(Boolean);
    let info;
    try {
      info = JSON.parse(lines[lines.length - 1]);
    } catch {
      continue;
    }
    if (!/^\d+\.\d+\.\d+$/.test(info.version || '')) continue;
    const [major, minor] = info.version.split('.').map(Number);
    if (major < 3 || (major === 3 && minor < 9)) continue;

    pythonCache = {
      command: candidate.command,
      args: candidate.args,
      version: info.version,
      executable: info.executable || candidate.command,
      display: [candidate.command, ...candidate.args].join(' '),
    };
    return pythonCache;
  }

  pythonCache = null;
  return null;
}

function atlasVersion() {
  try {
    const match = fs
      .readFileSync(ATLAS, 'utf8')
      .match(/^VERSION\s*=\s*"([^"]+)"/m);
    return match ? match[1] : null;
  } catch {
    return null;
  }
}

function pad(value, width) {
  const text = String(value);
  return text.length >= width ? text : text + ' '.repeat(width - text.length);
}

function printHeader(python) {
  console.log(`CodeAtlas ${PKG.version}`);
  console.log(
    `  python  ${python ? `${python.version}  ${python.executable}` : 'not found (install Python 3.9+)'}`
  );
  const engine = atlasVersion();
  if (engine) console.log(`  engine  atlas.py ${engine}`);
}

function countResults(results) {
  const counts = {
    changed: 0,
    current: 0,
    skipped: 0,
    errors: 0,
  };
  for (const result of results) {
    if (result.error) counts.errors += 1;
    else if (result.action === 'current') counts.current += 1;
    else if (result.action === 'skip') counts.skipped += 1;
    else counts.changed += 1;
  }
  return counts;
}

function printResults(results, options = {}) {
  const width = Math.max(
    ...results.map((result) => result.target.agent.label.length),
    8
  );
  for (const result of results) {
    const action = result.error
      ? 'error'
      : result.action;
    let note = result.note || result.error || '';
    if (!note && result.inspection && result.inspection.linked) note = 'linked';
    console.log(
      `  ${pad(action, 13)} ${pad(result.target.agent.label, width)}  ${displayPath(result.target.dest)}${note ? `  (${note})` : ''}`
    );
  }
  if (options.dryRun) {
    console.log('');
    console.log('Dry run: no files were written.');
  }
}

function printInstallHelp() {
  console.log(`Install the CodeAtlas skill for coding agents.

Usage:
  code-atlas install [options]

Options:
  --agent <list>     agents to install for: opencode, claude, codex, cursor, agents
                     (repeatable or comma-separated; default: all)
  --all              explicit alias for the default all-agent install
  --target <dir>     parent skills directory (repeatable; receives code-atlas/)
  --project          install into the current repository instead of globally
  --project-dir <d>  repository for --project (default: current directory)
  --force            replace an existing install, including unmanaged copies
  --link             keep one canonical copy and link the other agents to it
  --canonical <dir>  canonical skill directory for --link
  --dry-run          show what would happen without writing
  --json             machine-readable result
  --quiet            only print the summary and warnings
  -h, --help         show this help

Examples:
  npx code-atlas install
  npx code-atlas install --agent claude,codex
  npx code-atlas install --project --agent claude
  npx code-atlas install --link --force
  npx code-atlas install --target "$HOME/.claude/skills" --force

Default global destinations:
  OpenCode      ~/.config/opencode/skills/code-atlas
  Claude Code   ~/.claude/skills/code-atlas
  Codex CLI     ~/.codex/skills/code-atlas
  Cursor        ~/.cursor/skills/code-atlas
  Universal     ~/.agents/skills/code-atlas`);
}

function printStatusHelp() {
  console.log(`Show where CodeAtlas is installed and whether Python is available.

Usage:
  code-atlas status [options]

Options:
  --agent <list>     only show these agents
  --target <dir>     also inspect a custom parent skills directory
  --project          show project installs instead of global installs
  --project-dir <d>  repository for --project (default: current directory)
  --json             machine-readable result
  -h, --help         show this help`);
}

function printUninstallHelp() {
  console.log(`Remove CodeAtlas skill copies.

Usage:
  code-atlas uninstall [options]

Options:
  --agent <list>     only remove these agents' copies
  --all              explicit alias for the default all-agent removal
  --target <dir>     parent skills directory (repeatable)
  --project          remove the project install instead of global installs
  --project-dir <d>  repository for --project (default: current directory)
  --unmanaged        also remove copies that were not installed by this CLI
  --dry-run          show what would happen without writing
  --json             machine-readable result
  --quiet            only print the summary
  -h, --help         show this help

Repository indexes (CODEATLAS.md and .code-atlas/) are never removed.`);
}

function installCommand(argv) {
  const values = parseCommandArgs(argv, {
    all: { type: 'boolean', default: false },
    agent: { type: 'string', multiple: true },
    target: { type: 'string', multiple: true },
    project: { type: 'boolean', default: false },
    'project-dir': { type: 'string' },
    force: { type: 'boolean', default: false },
    link: { type: 'boolean', default: false },
    canonical: { type: 'string' },
    'dry-run': { type: 'boolean', default: false },
    json: { type: 'boolean', default: false },
    quiet: { type: 'boolean', default: false },
    help: { type: 'boolean', short: 'h', default: false },
  });

  if (values.help) {
    printInstallHelp();
    return 0;
  }
  if (values.link && values.project) {
    throw new Error('--link is available for global installs only');
  }

  const python = findPython();
  const targets = resolveTargets(values);
  const options = {
    force: Boolean(values.force),
    dryRun: Boolean(values['dry-run']),
  };
  const results = [];

  if (values.link) {
    const canonical = values.canonical
      ? path.join(expandHome(values.canonical), NAME)
      : path.join(getHome(), '.agents', 'skills', NAME);
    const canonicalTarget = {
      agent: { id: 'agents', label: 'Universal' },
      scope: 'global',
      dest: canonical,
    };
    try {
      const installed = installPayload(canonical, options);
      results.push({ target: canonicalTarget, ...installed });
    } catch (error) {
      results.push({ target: canonicalTarget, error: error.message });
    }
    if (!options.dryRun && !fs.existsSync(path.join(canonical, 'scripts', 'atlas.py'))) {
      throw new Error(`canonical install is incomplete: ${canonical}`);
    }
    for (const target of targets) {
      if (samePath(target.dest, canonical)) continue;
      try {
        const linked = linkPayload(target.dest, canonical, options);
        results.push({ target, ...linked });
      } catch (error) {
        results.push({ target, error: error.message });
      }
    }
  } else {
    for (const target of targets) {
      try {
        const installed = installOne(target, options);
        results.push({ target, ...installed });
      } catch (error) {
        results.push({ target, error: error.message });
      }
    }
  }

  const counts = countResults(results);
  if (values.json) {
    console.log(
      JSON.stringify(
        {
          name: NAME,
          version: PKG.version,
          engine: atlasVersion(),
          python: python
            ? { version: python.version, executable: python.executable }
            : null,
          dryRun: options.dryRun,
          targets: results.map((result) => ({
            agent: result.target.agent.id,
            label: result.target.agent.label,
            scope: result.target.scope,
            path: result.target.dest,
            action: result.error ? 'error' : result.action,
            state: result.inspection ? result.inspection.state : undefined,
            note: result.note || result.error || undefined,
          })),
          summary: counts,
        },
        null,
        2
      )
    );
  } else {
    if (!values.quiet) {
      printHeader(python);
      console.log('');
      printResults(results, { dryRun: options.dryRun });
      console.log('');
    }
    const verb = options.dryRun ? 'Would change' : 'Changed';
    console.log(
      `${verb} ${counts.changed} | current ${counts.current} | skipped ${counts.skipped} | errors ${counts.errors}`
    );
    if (!python) {
      console.error('warning: Python 3.9+ was not found. Install Python before using the skill.');
    }
    if (!options.dryRun && counts.errors === 0) {
      console.log('Restart your agent to pick up the skill. Verify with: code-atlas status');
    }
  }

  return counts.errors > 0 ? 1 : 0;
}

function statusCommand(argv) {
  const values = parseCommandArgs(argv, {
    agent: { type: 'string', multiple: true },
    target: { type: 'string', multiple: true },
    project: { type: 'boolean', default: false },
    'project-dir': { type: 'string' },
    json: { type: 'boolean', default: false },
    help: { type: 'boolean', short: 'h', default: false },
  });

  if (values.help) {
    printStatusHelp();
    return 0;
  }

  const targets = [];
  if ((values.target || []).length) {
    targets.push(...customTargets(values));
  } else if (values.project) {
    targets.push(...projectTargets(values));
  } else {
    targets.push(...globalTargets(values));
    const projectRoot = values['project-dir']
      ? expandHome(values['project-dir'])
      : process.cwd();
    for (const agent of selectedAgents(values)) {
      if (!agent.projectParent) continue;
      const dest = path.join(projectRoot, agent.projectParent, NAME);
      if (fs.existsSync(dest)) {
        targets.push({ agent, scope: 'project', dest });
      }
    }
  }

  const entries = dedupeTargets(targets).map((target) => {
    const inspection = inspectTarget(target.dest);
    return {
      target,
      state: inspection.state,
      version: inspection.version || '',
      linked: Boolean(inspection.linked),
      realPath: inspection.realPath || '',
    };
  });

  const python = findPython();
  const engine = atlasVersion();
  const healthy = Boolean(python) && entries.some((entry) => entry.state === 'current');

  if (values.json) {
    console.log(
      JSON.stringify(
        {
          name: NAME,
          version: PKG.version,
          engine,
          python: python
            ? { version: python.version, executable: python.executable }
            : null,
          healthy,
          targets: entries.map((entry) => ({
            agent: entry.target.agent.id,
            label: entry.target.agent.label,
            scope: entry.target.scope,
            path: entry.target.dest,
            state: entry.state,
            version: entry.version || undefined,
            linked: entry.linked,
            realPath: entry.linked ? entry.realPath : undefined,
          })),
        },
        null,
        2
      )
    );
    return healthy ? 0 : 1;
  }

  printHeader(python);
  console.log('');
  const agentWidth = Math.max(
    ...entries.map((entry) => entry.target.agent.label.length),
    8
  );
  console.log(
    `${pad('AGENT', agentWidth)}  ${pad('SCOPE', 7)}  ${pad('STATE', 10)}  ${pad('VERSION', 7)}  PATH`
  );
  for (const entry of entries) {
    let pathText = displayPath(entry.target.dest);
    if (entry.linked && entry.realPath) {
      pathText += ` -> ${displayPath(entry.realPath)}`;
    }
    console.log(
      `${pad(entry.target.agent.label, agentWidth)}  ${pad(entry.target.scope, 7)}  ${pad(entry.state, 10)}  ${pad(entry.version || '-', 7)}  ${pathText}`
    );
  }

  const current = entries.filter((entry) => entry.state === 'current').length;
  const outdated = entries.filter((entry) => entry.state === 'outdated').length;
  const missing = entries.filter((entry) => entry.state === 'missing').length;
  console.log('');
  console.log(
    `${current} current | ${outdated} outdated | ${missing} missing | ${entries.length - current - outdated - missing} other`
  );
  if (!python) {
    console.error('Python 3.9+ was not found. Install Python before running the engine.');
  }
  if (!healthy) {
    console.log('Install or update with: npx code-atlas install --force');
  }
  return healthy ? 0 : 1;
}

function uninstallCommand(argv) {
  const values = parseCommandArgs(argv, {
    all: { type: 'boolean', default: false },
    agent: { type: 'string', multiple: true },
    target: { type: 'string', multiple: true },
    project: { type: 'boolean', default: false },
    'project-dir': { type: 'string' },
    unmanaged: { type: 'boolean', default: false },
    'dry-run': { type: 'boolean', default: false },
    json: { type: 'boolean', default: false },
    quiet: { type: 'boolean', default: false },
    help: { type: 'boolean', short: 'h', default: false },
  });

  if (values.help) {
    printUninstallHelp();
    return 0;
  }

  const targets = resolveTargets(values);
  const results = [];
  for (const target of targets) {
    const inspection = inspectTarget(target.dest);
    if (inspection.state === 'missing') {
      results.push({ target, action: 'missing', inspection });
      continue;
    }
    const managed =
      inspection.state === 'current' || inspection.state === 'outdated';
    if (!managed && !values.unmanaged) {
      results.push({
        target,
        action: 'skip',
        inspection,
        note: 'unmanaged; use --unmanaged to remove',
      });
      continue;
    }
    if (values['dry-run']) {
      results.push({ target, action: 'would-remove', inspection });
      continue;
    }
    try {
      removePath(target.dest);
      results.push({ target, action: 'removed', inspection });
    } catch (error) {
      results.push({ target, action: 'error', inspection, error: error.message });
    }
  }

  const removed = results.filter((result) => result.action === 'removed').length;
  const skipped = results.filter((result) => result.action === 'skip').length;
  const errors = results.filter((result) => result.action === 'error').length;

  if (values.json) {
    console.log(
      JSON.stringify(
        {
          name: NAME,
          version: PKG.version,
          dryRun: Boolean(values['dry-run']),
          targets: results.map((result) => ({
            agent: result.target.agent.id,
            label: result.target.agent.label,
            scope: result.target.scope,
            path: result.target.dest,
            state: result.inspection.state,
            action: result.action,
            note: result.note || result.error || undefined,
          })),
          summary: { removed, skipped, errors },
        },
        null,
        2
      )
    );
  } else {
    if (!values.quiet) {
      console.log(`CodeAtlas ${PKG.version} uninstall`);
      console.log('');
      for (const result of results) {
        if (result.action === 'missing') continue;
        const note = result.note || result.error || '';
        console.log(
          `  ${pad(result.action, 13)} ${pad(result.target.agent.label, 12)}  ${displayPath(result.target.dest)}${note ? `  (${note})` : ''}`
        );
      }
      console.log('');
    }
    const verb = values['dry-run'] ? 'Would remove' : 'Removed';
    console.log(`${verb} ${removed} | skipped ${skipped} | errors ${errors}`);
    if (!values['dry-run'] && removed) {
      console.log('Repository indexes (CODEATLAS.md, .code-atlas/) were not touched.');
    }
  }

  return errors > 0 ? 1 : 0;
}

function agentsCommand(argv) {
  const values = parseCommandArgs(argv, {
    json: { type: 'boolean', default: false },
    help: { type: 'boolean', short: 'h', default: false },
  });
  if (values.help) {
    console.log('Usage: code-atlas agents [--json]');
    return 0;
  }
  const agents = agentDefinitions().map((agent) => ({
    id: agent.id,
    label: agent.label,
    global: path.join(agent.globalParent, NAME),
    project: agent.projectParent
      ? path.join(process.cwd(), agent.projectParent, NAME)
      : null,
  }));
  if (values.json) {
    console.log(JSON.stringify(agents, null, 2));
    return 0;
  }
  console.log('AGENT        GLOBAL SKILL PATH');
  for (const agent of agents) {
    console.log(`${pad(agent.id, 12)} ${displayPath(agent.global)}`);
  }
  return 0;
}

function parseCommandArgs(argv, options) {
  try {
    const parsed = parseArgs({
      args: argv,
      options,
      strict: true,
      allowPositionals: false,
    });
    return parsed.values;
  } catch (error) {
    throw new Error(`${error.message}\nRun "code-atlas help" for usage.`);
  }
}

function printMainHelp() {
  console.log(`CodeAtlas ${PKG.version} - a map before the read.

Usage:
  code-atlas <command> [options]

Skill management:
  install      install the skill for OpenCode, Claude Code, Codex, and Cursor
  status       show install paths, versions, and Python availability
  uninstall    remove managed skill copies
  agents       list supported agents and their paths

Atlas engine (requires Python 3.9+):
  init         create config, .gitignore entry, and build
  build        build or refresh the index
  update       incremental refresh after edits
  map          print the compact map
  where <sym>  locate a symbol
  impact <x>   reverse dependencies, risk, and affected tests
  path <a> <b> shortest dependency path
  pack <area>  related files under a token budget
  diagram      write Mermaid and interactive HTML
  doctor       check index freshness and coverage
  stats        index statistics

Examples:
  npx code-atlas install
  npm i -g code-atlas
  code-atlas install --agent claude,codex
  code-atlas build
  code-atlas where Session.send
  code-atlas impact src/api.py

Run "code-atlas help <command>" for command-specific help.
Atlas commands also accept -C <repo>, --json, --no-color, and their own flags.`);
}

function runAtlas(args) {
  const python = findPython();
  if (!python) {
    console.error('CodeAtlas needs Python 3.9+ to run the engine.');
    console.error('Install Python from https://www.python.org/downloads/ and retry.');
    console.error('Or set CODEATLAS_PYTHON to the interpreter path.');
    return 2;
  }

  const child = spawn(
    python.command,
    [...python.args, ATLAS, ...args],
    {
      stdio: 'inherit',
      windowsHide: true,
      env: { ...process.env, PYTHONIOENCODING: 'utf-8' },
    }
  );
  child.on('error', (error) => {
    console.error(`failed to start Python: ${error.message}`);
    process.exitCode = 2;
  });
  child.on('exit', (code, signal) => {
    if (signal) {
      process.exitCode = 1;
    } else {
      process.exitCode = code === null ? 1 : code;
    }
  });
  return 0;
}

function main(argv) {
  if (!argv.length) {
    printMainHelp();
    return 0;
  }

  const first = argv[0];
  if (first === '--version' || first === '-v' || first === '-V' || first === 'version') {
    console.log(PKG.version);
    return 0;
  }
  if (first === '--help' || first === '-h' || first === 'help') {
    if (argv[1] === 'install') printInstallHelp();
    else if (argv[1] === 'status') printStatusHelp();
    else if (argv[1] === 'uninstall') printUninstallHelp();
    else if (argv[1] === 'agents') console.log('Usage: code-atlas agents [--json]');
    else printMainHelp();
    return 0;
  }
  if (first === 'install') return installCommand(argv.slice(1));
  if (first === 'status') return statusCommand(argv.slice(1));
  if (first === 'uninstall') return uninstallCommand(argv.slice(1));
  if (first === 'agents') return agentsCommand(argv.slice(1));

  if (ATLAS_COMMANDS.has(first)) {
    return runAtlas(argv);
  }

  console.error(`unknown command: ${first}`);
  console.error('Run "code-atlas help" for usage.');
  return 2;
}

if (require.main === module) {
  try {
    const code = main(process.argv.slice(2));
    if (typeof code === 'number') process.exitCode = code;
  } catch (error) {
    console.error(`error: ${error.message}`);
    process.exitCode = 2;
  }
}

module.exports = {
  agentDefinitions,
  expandHome,
  findPython,
  inspectTarget,
  installPayload,
  main,
  parseCommandArgs,
  projectTargets,
  resolveTargets,
  selectedAgents,
};
