import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import test from 'node:test';

import {
  EXPECTED_NPM_VERSION,
  EXPECTED_NODE_VERSION,
  detectNpmVersion,
  evaluateNodeVersion,
  evaluateNpmVersion,
  formatFailure,
  parseNpmVersionOutput,
  resolveBundledNpmPath,
  validateToolchain,
} from './validate-node-toolchain.mjs';

const scriptDir = dirname(fileURLToPath(import.meta.url));
const validatorScript = join(scriptDir, 'validate-node-toolchain.mjs');

function mockSpawn(stdout, { status = 0, stderr = '', error = null } = {}) {
  return () => ({
    stdout,
    stderr,
    status,
    error,
  });
}

test('accepts the exact project Node and npm versions', () => {
  const result = validateToolchain({
    nodeVersion: EXPECTED_NODE_VERSION,
    spawnImpl: mockSpawn(`${EXPECTED_NPM_VERSION}\n`),
  });
  assert.equal(result.ok, true);
  assert.equal(result.nodeVersion, EXPECTED_NODE_VERSION);
  assert.equal(result.npmVersion, EXPECTED_NPM_VERSION);
});

test('rejects Node major too old', () => {
  const result = evaluateNodeVersion('v23.9.0');
  assert.equal(result.ok, false);
  assert.equal(result.reason, 'node-version-mismatch');
  assert.equal(result.actual, 'v23.9.0');
});

test('rejects Node 24 with patch mismatch', () => {
  const result = evaluateNodeVersion('v24.8.0');
  assert.equal(result.ok, false);
  assert.equal(result.reason, 'node-version-mismatch');
  assert.equal(result.expected, EXPECTED_NODE_VERSION);
});

test('rejects npm 11.6.0', () => {
  const result = evaluateNpmVersion('11.6.0');
  assert.equal(result.ok, false);
  assert.equal(result.reason, 'npm-version-mismatch');
});

test('rejects npm 11.12.1', () => {
  const result = evaluateNpmVersion('11.12.1');
  assert.equal(result.ok, false);
  assert.equal(result.reason, 'npm-version-mismatch');
});

test('rejects npm 11.13.0 even though extraneous bug is fixed', () => {
  const result = evaluateNpmVersion('11.13.0');
  assert.equal(result.ok, false);
  assert.equal(result.reason, 'npm-version-mismatch');
});

test('rejects npm 12', () => {
  const result = evaluateNpmVersion('12.0.0');
  assert.equal(result.ok, false);
  assert.equal(result.reason, 'npm-version-mismatch');
});

test('rejects malformed npm output', () => {
  const parsed = parseNpmVersionOutput('not-a-version');
  assert.equal(parsed.ok, false);
  assert.equal(parsed.reason, 'npm-version-malformed');
});

test('rejects npm command non-zero exit', () => {
  const result = detectNpmVersion({ spawnImpl: mockSpawn('', { status: 1 }) });
  assert.equal(result.ok, false);
  assert.equal(result.reason, 'npm-command-nonzero');
});

test('rejects npm command timeout', () => {
  const result = detectNpmVersion({
    spawnImpl: mockSpawn('', { error: Object.assign(new Error('timeout'), { code: 'ETIMEDOUT' }) }),
  });
  assert.equal(result.ok, false);
  assert.equal(result.reason, 'npm-command-timeout');
});

test('rejects empty npm output', () => {
  const parsed = parseNpmVersionOutput('');
  assert.equal(parsed.ok, false);
  assert.equal(parsed.reason, 'npm-version-empty');
});

test('rejects npm output with extra lines', () => {
  const parsed = parseNpmVersionOutput(`${EXPECTED_NPM_VERSION}\nextra-line`);
  assert.equal(parsed.ok, false);
  assert.equal(parsed.reason, 'npm-version-multiline');
});

test('resolveBundledNpmPath prefers npm adjacent to the active node binary', () => {
  const npmPath = resolveBundledNpmPath(process.execPath);
  assert.match(npmPath, /npm(\.cmd)?$/);
});

test('rejects npm command killed by signal', () => {
  const result = detectNpmVersion({
    spawnImpl: () => ({ stdout: '', stderr: '', status: null, signal: 'SIGTERM', error: null }),
  });
  assert.equal(result.ok, false);
  assert.equal(result.reason, 'npm-command-failed');
});

test('failure messages do not leak PATH or HOME canary values', () => {
  const failure = formatFailure({
    ok: false,
    reason: 'npm-command-failed',
  });
  assert.match(failure, /npm-command-failed/);
  assert.doesNotMatch(failure, /canary-path-token/);
  assert.doesNotMatch(failure, /\/Users\//);
});

test('CLI succeeds from another working directory when toolchain matches', () => {
  const result = spawnSync(process.execPath, [validatorScript], {
    cwd: '/',
    encoding: 'utf8',
    env: {
      ...process.env,
      PATH: `${dirname(process.execPath)}:${process.env.PATH ?? ''}`,
    },
  });

  if (process.version !== EXPECTED_NODE_VERSION) {
    assert.equal(result.status, 1);
    assert.match(result.stderr, /node-version-mismatch/);
    return;
  }

  assert.equal(result.status, 0);
  assert.match(result.stdout, /toolchain-ok node=v24\.19\.0 npm=11\.17\.0/);
});

test('importing the module does not execute the CLI', () => {
  assert.equal(typeof validateToolchain, 'function');
  assert.equal(typeof parseNpmVersionOutput, 'function');
});
