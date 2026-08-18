import assert from 'node:assert/strict';
import { mkdtempSync, mkdirSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import test from 'node:test';

import {
  countDependencyProblems,
  evaluateInstalledTree,
  formatFailure,
  mergeInstalledTreeCounts,
  nodeModulesInstalled,
  parseExtraneousQuery,
  runNpmJson,
  scanDependencyTree,
  validateInstalledTree,
} from './validate-installed-dependency-tree.mjs';

test('accepts a clean installed tree', () => {
  const result = evaluateInstalledTree({
    extraneousCount: 0,
    invalidCount: 0,
    unmetCount: 0,
  });
  assert.equal(result.ok, true);
});

test('rejects one extraneous package', () => {
  const result = evaluateInstalledTree({
    extraneousCount: 1,
    invalidCount: 0,
    unmetCount: 0,
  });
  assert.equal(result.ok, false);
  assert.equal(result.reason, 'extraneous-packages');
  assert.equal(result.extraneousCount, 1);
});

test('rejects multiple extraneous packages', () => {
  const result = evaluateInstalledTree({
    extraneousCount: 2,
    invalidCount: 0,
    unmetCount: 0,
  });
  assert.equal(result.ok, false);
  assert.equal(result.extraneousCount, 2);
});

test('rejects invalid dependencies', () => {
  const result = evaluateInstalledTree({
    extraneousCount: 0,
    invalidCount: 1,
    unmetCount: 0,
  });
  assert.equal(result.ok, false);
  assert.equal(result.reason, 'invalid-dependencies');
});

test('rejects unmet dependencies', () => {
  const result = evaluateInstalledTree({
    extraneousCount: 0,
    invalidCount: 0,
    unmetCount: 1,
  });
  assert.equal(result.ok, false);
  assert.equal(result.reason, 'unmet-dependencies');
});

test('rejects @emnapi/runtime extraneous the same as any other package', () => {
  const extraneous = parseExtraneousQuery([
    { name: '@emnapi/runtime', version: '1.11.2' },
  ]);
  const result = evaluateInstalledTree({
    extraneousCount: extraneous.length,
    invalidCount: 0,
    unmetCount: 0,
  });
  assert.equal(result.ok, false);
  assert.equal(result.reason, 'extraneous-packages');
});

test('parses npm ls problems from non-zero exits when JSON is valid', () => {
  const counts = countDependencyProblems([
    'invalid: left-pad@1.0.0 /tmp/node_modules/left-pad',
    'missing: right-pad@1.0.0, required by demo',
  ]);
  assert.equal(counts.invalid, 1);
  assert.equal(counts.unmet, 1);
});

test('validateInstalledTree handles npm ls non-zero with valid problems JSON', () => {
  const cwd = mkdtempSync(join(tmpdir(), 'installed-tree-'));
  mkdirSync(join(cwd, 'node_modules/react'), { recursive: true });

  const result = validateInstalledTree({
    cwd,
    spawnImpl: (cmd, args) => {
      if (args[0] === 'query') {
        return { stdout: '[]', stderr: '', status: 0, error: null };
      }
      if (args[0] === 'ls') {
        return {
          stdout: JSON.stringify({
            name: 'demo',
            problems: ['invalid: react@19.0.0'],
          }),
          stderr: '',
          status: 1,
          error: null,
        };
      }
      return { stdout: '', stderr: 'unexpected', status: 1, error: null };
    },
  });

  assert.equal(result.ok, false);
  assert.equal(result.reason, 'invalid-dependencies');
  rmSync(cwd, { recursive: true, force: true });
});

test('rejects malformed npm query JSON', () => {
  const cwd = mkdtempSync(join(tmpdir(), 'installed-tree-'));
  mkdirSync(join(cwd, 'node_modules/react'), { recursive: true });

  const result = validateInstalledTree({
    cwd,
    spawnImpl: (_cmd, args) => {
      if (args[0] === 'query') {
        return { stdout: '{not-json', stderr: '', status: 0, error: null };
      }
      return { stdout: '{}', stderr: '', status: 0, error: null };
    },
  });

  assert.equal(result.ok, false);
  assert.match(result.reason, /malformed/);
  rmSync(cwd, { recursive: true, force: true });
});

test('rejects malformed npm ls JSON', () => {
  const cwd = mkdtempSync(join(tmpdir(), 'installed-tree-'));
  mkdirSync(join(cwd, 'node_modules/react'), { recursive: true });

  const result = validateInstalledTree({
    cwd,
    spawnImpl: (_cmd, args) => {
      if (args[0] === 'query') {
        return { stdout: '[]', stderr: '', status: 0, error: null };
      }
      return { stdout: '[]', stderr: '', status: 1, error: null };
    },
  });

  assert.equal(result.ok, false);
  assert.match(result.reason, /npm-ls/);
  rmSync(cwd, { recursive: true, force: true });
});

test('rejects subprocess timeout', () => {
  const cwd = mkdtempSync(join(tmpdir(), 'installed-tree-'));
  mkdirSync(join(cwd, 'node_modules/react'), { recursive: true });

  const result = validateInstalledTree({
    cwd,
    spawnImpl: () => ({
      stdout: '',
      stderr: '',
      status: null,
      error: Object.assign(new Error('timeout'), { code: 'ETIMEDOUT' }),
    }),
  });

  assert.equal(result.ok, false);
  assert.equal(result.reason, 'npm-command-timeout');
  rmSync(cwd, { recursive: true, force: true });
});

test('rejects subprocess spawn failure', () => {
  const cwd = mkdtempSync(join(tmpdir(), 'installed-tree-'));
  mkdirSync(join(cwd, 'node_modules/react'), { recursive: true });

  const result = validateInstalledTree({
    cwd,
    spawnImpl: () => ({
      stdout: '',
      stderr: '',
      status: null,
      error: new Error('spawn ENOENT'),
    }),
  });

  assert.equal(result.ok, false);
  assert.equal(result.reason, 'npm-command-failed');
  rmSync(cwd, { recursive: true, force: true });
});

test('rejects oversized npm output', () => {
  const cwd = mkdtempSync(join(tmpdir(), 'installed-tree-'));
  mkdirSync(join(cwd, 'node_modules/react'), { recursive: true });

  const result = validateInstalledTree({
    cwd,
    maxOutputBytes: 16,
    spawnImpl: () => ({
      stdout: 'x'.repeat(32),
      stderr: '',
      status: 0,
      error: null,
    }),
  });

  assert.equal(result.ok, false);
  assert.equal(result.reason, 'npm-output-oversized');
  rmSync(cwd, { recursive: true, force: true });
});

test('rejects unexpected npm ls schema', () => {
  const cwd = mkdtempSync(join(tmpdir(), 'installed-tree-'));
  mkdirSync(join(cwd, 'node_modules/react'), { recursive: true });

  const result = validateInstalledTree({
    cwd,
    spawnImpl: (_cmd, args) => {
      if (args[0] === 'query') {
        return { stdout: '[]', stderr: '', status: 0, error: null };
      }
      return { stdout: JSON.stringify([]), stderr: '', status: 0, error: null };
    },
  });

  assert.equal(result.ok, false);
  assert.equal(result.reason, 'npm-ls-schema-invalid');
  rmSync(cwd, { recursive: true, force: true });
});

test('rejects empty node_modules before npm ci', () => {
  const cwd = mkdtempSync(join(tmpdir(), 'installed-tree-'));
  const result = validateInstalledTree({ cwd });
  assert.equal(result.ok, false);
  assert.equal(result.reason, 'installed-tree-missing');
  rmSync(cwd, { recursive: true, force: true });
});

test('nodeModulesInstalled requires non-hidden entries', () => {
  const cwd = mkdtempSync(join(tmpdir(), 'installed-tree-'));
  mkdirSync(join(cwd, 'node_modules'), { recursive: true });
  assert.equal(nodeModulesInstalled(cwd), false);
  mkdirSync(join(cwd, 'node_modules/react'), { recursive: true });
  assert.equal(nodeModulesInstalled(cwd), true);
  rmSync(cwd, { recursive: true, force: true });
});

test('failure output does not leak canary package names from problems text', () => {
  const failure = formatFailure({
    ok: false,
    reason: 'extraneous-packages',
    extraneousCount: 1,
    invalidCount: 0,
    unmetCount: 0,
  });
  assert.match(failure, /extraneous=1/);
  assert.doesNotMatch(failure, /canary-package-name/);
  assert.doesNotMatch(failure, /\/Users\//);
});

test('runNpmJson never enables shell execution', () => {
  const calls = [];
  runNpmJson(['query', ':extraneous', '--json'], {
    cwd: tmpdir(),
    spawnImpl: (cmd, args, options) => {
      calls.push({ cmd, args, shell: options.shell });
      return { stdout: '[]', stderr: '', status: 0, error: null };
    },
  });
  assert.equal(calls.length, 1);
  assert.equal(calls[0].shell, false);
});

test('merges multiple problem categories in one failure summary', () => {
  const result = evaluateInstalledTree({
    extraneousCount: 2,
    invalidCount: 1,
    unmetCount: 3,
  });
  assert.equal(result.ok, false);
  assert.equal(result.reason, 'extraneous-packages');
  assert.equal(result.invalidCount, 1);
  assert.equal(result.unmetCount, 3);
});

test('parseExtraneousQuery rejects unexpected schema', () => {
  assert.throws(() => parseExtraneousQuery({}), /extraneous-schema-invalid/);
  assert.throws(() => parseExtraneousQuery(null), /extraneous-schema-invalid/);
});

test('scanDependencyTree detects nested extraneous and missing markers', () => {
  const counts = scanDependencyTree({
    name: 'demo',
    dependencies: {
      react: {
        name: 'react',
        version: '19.0.0',
        extraneous: true,
        dependencies: {
          scheduler: {
            name: 'scheduler',
            version: '0.23.0',
            missing: true,
          },
        },
      },
    },
  });
  assert.equal(counts.extraneous, 1);
  assert.equal(counts.unmet, 1);
});

test('mergeInstalledTreeCounts preserves failures from any source', () => {
  const merged = mergeInstalledTreeCounts(0, { invalid: 0, unmet: 0 }, { extraneous: 1, invalid: 0, unmet: 0 });
  assert.equal(merged.extraneousCount, 1);
  const result = evaluateInstalledTree(merged);
  assert.equal(result.ok, false);
});

test('rejects npm ls empty stdout as execution failure', () => {
  const cwd = mkdtempSync(join(tmpdir(), 'installed-tree-'));
  mkdirSync(join(cwd, 'node_modules/react'), { recursive: true });

  const result = validateInstalledTree({
    cwd,
    spawnImpl: (_cmd, args) => {
      if (args[0] === 'query') {
        return { stdout: '[]', stderr: '', status: 0, error: null };
      }
      return { stdout: '', stderr: 'failed', status: 1, error: null };
    },
  });

  assert.equal(result.ok, false);
  assert.equal(result.reason, 'npm-ls-execution-failure');
  rmSync(cwd, { recursive: true, force: true });
});

test('scanDependencyTree enforces node limits', () => {
  assert.throws(
    () => scanDependencyTree({ name: 'demo', dependencies: { a: { name: 'a' } } }, { nodes: 50_000, extraneous: 0, invalid: 0, unmet: 0 }, 0, { maxNodes: 1 }),
    /npm-ls-tree-limit-exceeded/,
  );
});

test('shell injection-like package names stay out of failure summaries', () => {
  const cwd = mkdtempSync(join(tmpdir(), 'installed-tree-'));
  mkdirSync(join(cwd, 'node_modules', 'pkg'), { recursive: true });

  const result = validateInstalledTree({
    cwd,
    spawnImpl: (_cmd, args) => {
      if (args[0] === 'query') {
        return {
          stdout: JSON.stringify([{ name: '"; rm -rf /; echo "', version: '1.0.0' }]),
          stderr: '',
          status: 0,
          error: null,
        };
      }
      return { stdout: JSON.stringify({ name: 'demo', problems: [] }), stderr: '', status: 0, error: null };
    },
  });

  const failure = formatFailure(result);
  assert.match(failure, /extraneous=1/);
  assert.doesNotMatch(failure, /rm -rf/);
  rmSync(cwd, { recursive: true, force: true });
});
