'use strict';

const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const { spawnSync } = require('node:child_process');
const test = require('node:test');

const ROOT = path.resolve(__dirname, '..');
const BIN = path.join(ROOT, 'bin', 'code-atlas.js');
const PKG = JSON.parse(fs.readFileSync(path.join(ROOT, 'package.json'), 'utf8'));

function tempDir(prefix = 'code-atlas-cli-') {
  return fs.mkdtempSync(path.join(os.tmpdir(), prefix));
}

function run(args, options = {}) {
  const env = {
    ...process.env,
    CODEATLAS_HOME: options.home || tempDir('code-atlas-home-'),
    NO_COLOR: '1',
    ...options.env,
  };
  return spawnSync(process.execPath, [BIN, ...args], {
    cwd: options.cwd || ROOT,
    encoding: 'utf8',
    env,
    timeout: 120000,
    windowsHide: true,
  });
}

function json(result) {
  assert.equal(
    result.status,
    0,
    `command failed\nstdout:\n${result.stdout}\nstderr:\n${result.stderr}`
  );
  return JSON.parse(result.stdout);
}

test('--version prints the package version without Python', (t) => {
  const home = tempDir();
  t.after(() => fs.rmSync(home, { recursive: true, force: true }));
  const result = run(['--version'], { home });
  assert.equal(result.status, 0);
  assert.equal(result.stdout.trim(), PKG.version);
});

test('install, update, and uninstall a custom target', (t) => {
  const home = tempDir();
  const parent = path.join(home, 'skills');
  t.after(() => fs.rmSync(home, { recursive: true, force: true }));

  let result = json(run(['install', '--target', parent, '--json'], { home }));
  assert.equal(result.summary.changed, 1);
  assert.equal(result.targets[0].action, 'install');

  const dest = path.join(parent, 'code-atlas');
  assert.ok(fs.existsSync(path.join(dest, 'SKILL.md')));
  assert.ok(fs.existsSync(path.join(dest, 'scripts', 'atlas.py')));
  assert.ok(fs.existsSync(path.join(dest, 'references', 'agent-setup.md')));

  const manifestPath = path.join(dest, '.codeatlas-skill.json');
  let manifest = JSON.parse(fs.readFileSync(manifestPath, 'utf8'));
  assert.equal(manifest.name, 'code-atlas');
  assert.equal(manifest.version, PKG.version);

  result = json(run(['install', '--target', parent, '--json'], { home }));
  assert.equal(result.targets[0].action, 'current');
  assert.equal(result.summary.current, 1);

  manifest.version = '0.0.0';
  fs.writeFileSync(manifestPath, JSON.stringify(manifest));
  result = json(run(['install', '--target', parent, '--json'], { home }));
  assert.equal(result.targets[0].action, 'update');
  manifest = JSON.parse(fs.readFileSync(manifestPath, 'utf8'));
  assert.equal(manifest.version, PKG.version);

  result = json(run(['install', '--target', parent, '--json', '--force'], { home }));
  assert.equal(result.targets[0].action, 'reinstall');

  const status = json(run(['status', '--target', parent, '--json'], { home }));
  assert.equal(status.targets[0].state, 'current');

  result = json(run(['uninstall', '--target', parent, '--json'], { home }));
  assert.equal(result.summary.removed, 1);
  assert.equal(fs.existsSync(dest), false);
});

test('unmanaged copies are skipped unless forced', (t) => {
  const home = tempDir();
  const parent = path.join(home, 'skills');
  const dest = path.join(parent, 'code-atlas');
  fs.mkdirSync(dest, { recursive: true });
  fs.writeFileSync(path.join(dest, 'SKILL.md'), '---\nname: code-atlas\n---\n');
  t.after(() => fs.rmSync(home, { recursive: true, force: true }));

  let result = json(run(['install', '--target', parent, '--json'], { home }));
  assert.equal(result.targets[0].action, 'skip');
  assert.equal(fs.existsSync(path.join(dest, '.codeatlas-skill.json')), false);

  result = json(run(['uninstall', '--target', parent, '--json'], { home }));
  assert.equal(result.summary.skipped, 1);

  result = json(run(['install', '--target', parent, '--json', '--force'], { home }));
  assert.equal(result.targets[0].action, 'replace');
  assert.ok(fs.existsSync(path.join(dest, '.codeatlas-skill.json')));

  result = json(run(['uninstall', '--target', parent, '--json'], { home }));
  assert.equal(result.summary.removed, 1);
  assert.equal(fs.existsSync(dest), false);

  fs.mkdirSync(dest, { recursive: true });
  fs.writeFileSync(path.join(dest, 'README.md'), 'manual copy\n');
  result = json(run(['uninstall', '--target', parent, '--json', '--unmanaged'], { home }));
  assert.equal(result.summary.removed, 1);
  assert.equal(fs.existsSync(dest), false);
});

test('project installs land in the repository', (t) => {
  const home = tempDir();
  const project = path.join(home, 'repo');
  fs.mkdirSync(project, { recursive: true });
  t.after(() => fs.rmSync(home, { recursive: true, force: true }));

  let result = json(
    run(
      ['install', '--project', '--project-dir', project, '--agent', 'claude', '--json'],
      { home }
    )
  );
  assert.equal(result.targets[0].scope, 'project');
  const dest = path.join(project, '.claude', 'skills', 'code-atlas');
  assert.ok(fs.existsSync(path.join(dest, 'scripts', 'atlas.py')));

  const status = json(
    run(
      ['status', '--project', '--project-dir', project, '--agent', 'claude', '--json'],
      { home }
    )
  );
  assert.equal(status.targets.length, 1);
  assert.equal(status.targets[0].state, 'current');

  json(run(['uninstall', '--project', '--project-dir', project, '--agent', 'claude', '--json'], { home }));
  assert.equal(fs.existsSync(dest), false);
});

test('global link mode keeps one copy and links the agents', (t) => {
  const home = tempDir();
  t.after(() => fs.rmSync(home, { recursive: true, force: true }));

  const result = json(run(['install', '--link', '--force', '--json'], { home }));
  assert.equal(result.summary.errors, 0);

  const canonical = path.join(home, '.agents', 'skills', 'code-atlas');
  assert.ok(fs.existsSync(path.join(canonical, 'scripts', 'atlas.py')));

  const claude = path.join(home, '.claude', 'skills', 'code-atlas');
  assert.ok(fs.existsSync(claude));
  const action = result.targets.find((target) => target.agent === 'claude');
  assert.ok(['link', 'copied'].includes(action.action));

  const status = json(run(['status', '--json'], { home }));
  const states = Object.fromEntries(
    status.targets.map((target) => [target.agent, target.state])
  );
  for (const agent of ['opencode', 'claude', 'codex', 'cursor', 'agents']) {
    assert.equal(states[agent], 'current', `${agent} should be current`);
  }

  json(run(['uninstall', '--json'], { home }));
  assert.equal(fs.existsSync(canonical), false);
  assert.equal(fs.existsSync(claude), false);
});

test('engine commands are forwarded to Python', (t) => {
  const home = tempDir();
  const project = path.join(home, 'fixture');
  fs.mkdirSync(project, { recursive: true });
  fs.writeFileSync(
    path.join(project, 'app.py'),
    'def hello(name):\n    return f"hello {name}"\n'
  );
  t.after(() => fs.rmSync(home, { recursive: true, force: true }));

  let result = run(['init', '--no-build'], { home, cwd: project });
  assert.equal(result.status, 0, result.stderr);
  assert.ok(fs.existsSync(path.join(project, '.codeatlas.json')));

  result = run(['build', '--no-git'], { home, cwd: project });
  assert.equal(result.status, 0, result.stderr);
  assert.ok(fs.existsSync(path.join(project, 'CODEATLAS.md')));

  const stats = json(run(['stats', '--json'], { home, cwd: project }));
  assert.ok(stats.files >= 1);
  assert.ok(stats.symbols >= 1);
});
