import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';
import { readFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import test from 'node:test';

import {
  ALLOWED_REGISTRY_HOST,
  classifyResolvedSource,
  defaultLockfilePath,
  formatViolationMessage,
  validateLockfileRegistry,
} from './validate-lockfile-registry.mjs';

const scriptDir = dirname(fileURLToPath(import.meta.url));
const validatorScript = join(scriptDir, 'validate-lockfile-registry.mjs');

test('accepts official registry HTTPS tarball URLs', () => {
  const verdict = classifyResolvedSource(
    `https://${ALLOWED_REGISTRY_HOST}/react/-/react-19.0.0.tgz`,
  );
  assert.equal(verdict.ok, true);
});

test('rejects npmmirror host', () => {
  const verdict = classifyResolvedSource(
    'https://registry.npmmirror.com/react/-/react-19.0.0.tgz',
  );
  assert.equal(verdict.ok, false);
  assert.equal(verdict.reason, 'disallowed-host');
});

test('rejects HTTP official registry URLs', () => {
  const verdict = classifyResolvedSource(
    `http://${ALLOWED_REGISTRY_HOST}/react/-/react-19.0.0.tgz`,
  );
  assert.equal(verdict.ok, false);
  assert.equal(verdict.reason, 'http-protocol');
});

test('rejects hostname suffix spoof attempts', () => {
  const verdict = classifyResolvedSource(
    'https://registry.npmjs.org.attacker.example/react/-/react-19.0.0.tgz',
  );
  assert.equal(verdict.ok, false);
  assert.equal(verdict.reason, 'disallowed-host');
});

test('rejects URL userinfo', () => {
  const verdict = classifyResolvedSource(
    `https://token:secret@${ALLOWED_REGISTRY_HOST}/react/-/react-19.0.0.tgz`,
  );
  assert.equal(verdict.ok, false);
  assert.equal(verdict.reason, 'url-userinfo');
});

test('rejects non-default port', () => {
  const verdict = classifyResolvedSource(
    `https://${ALLOWED_REGISTRY_HOST}:444/react/-/react-19.0.0.tgz`,
  );
  assert.equal(verdict.ok, false);
  assert.equal(verdict.reason, 'non-default-port');
});

test('rejects query strings', () => {
  const verdict = classifyResolvedSource(
    `https://${ALLOWED_REGISTRY_HOST}/react/-/react-19.0.0.tgz?canary=1`,
  );
  assert.equal(verdict.ok, false);
  assert.equal(verdict.reason, 'url-query');
});

test('rejects URL fragments', () => {
  const verdict = classifyResolvedSource(
    `https://${ALLOWED_REGISTRY_HOST}/react/-/react-19.0.0.tgz#fragment`,
  );
  assert.equal(verdict.ok, false);
  assert.equal(verdict.reason, 'url-fragment');
});

test('rejects protocol-relative URLs', () => {
  const verdict = classifyResolvedSource(`//${ALLOWED_REGISTRY_HOST}/react/-/react-19.0.0.tgz`);
  assert.equal(verdict.ok, false);
  assert.equal(verdict.reason, 'protocol-relative-url');
});

test('rejects control characters', () => {
  const verdict = classifyResolvedSource(
    `https://${ALLOWED_REGISTRY_HOST}/react/\u0007-/react-19.0.0.tgz`,
  );
  assert.equal(verdict.ok, false);
  assert.equal(verdict.reason, 'control-character');
});

test('rejects non-string resolved values', () => {
  const verdict = classifyResolvedSource(123);
  assert.equal(verdict.ok, false);
  assert.equal(verdict.reason, 'non-string-resolved');
});

test('rejects encoded userinfo host confusion', () => {
  const verdict = classifyResolvedSource(
    `https://token%40evil.example@${ALLOWED_REGISTRY_HOST}/react/-/react-19.0.0.tgz`,
  );
  assert.equal(verdict.ok, false);
  assert.equal(verdict.reason, 'url-userinfo');
});

test('rejects git+https sources', () => {
  const verdict = classifyResolvedSource('git+https://github.com/example/repo.git');
  assert.equal(verdict.ok, false);
});

test('rejects file sources', () => {
  const verdict = classifyResolvedSource('file:../local-package.tgz');
  assert.equal(verdict.ok, false);
});

test('rejects malformed URLs', () => {
  const verdict = classifyResolvedSource('not-a-url');
  assert.equal(verdict.ok, false);
  assert.equal(verdict.reason, 'malformed-url');
});

test('allows missing resolved only for the workspace root entry', () => {
  const result = validateLockfileRegistry({
    packages: {
      '': { name: 'seller-ai-copilot-frontend' },
      'node_modules/react': {
        version: '19.0.0',
        resolved: `https://${ALLOWED_REGISTRY_HOST}/react/-/react-19.0.0.tgz`,
        integrity: 'sha512-example',
      },
    },
  });

  assert.equal(result.checked, 1);
  assert.deepEqual(result.violations, []);
});

test('error messages do not echo URL userinfo canaries', () => {
  const result = validateLockfileRegistry({
    packages: {
      'node_modules/react': {
        resolved: `https://canary-token:canary-secret@${ALLOWED_REGISTRY_HOST}/react/-/react-19.0.0.tgz`,
      },
    },
  });

  const message = formatViolationMessage(result.violations[0]);
  assert.match(message, /url-userinfo/);
  assert.doesNotMatch(message, /canary-token/);
  assert.doesNotMatch(message, /canary-secret/);
  assert.doesNotMatch(message, /https:\/\//);
});

test('fails when any package entry uses a disallowed source', () => {
  const result = validateLockfileRegistry({
    packages: {
      'node_modules/react': {
        resolved: `https://${ALLOWED_REGISTRY_HOST}/react/-/react-19.0.0.tgz`,
      },
      'node_modules/left-pad': {
        resolved: 'https://registry.npmmirror.com/left-pad/-/left-pad-1.0.0.tgz',
      },
    },
  });

  assert.equal(result.violations.length, 1);
  assert.equal(result.violations[0].packagePath, 'node_modules/left-pad');
});

test('returns accurate checked count for valid lockfiles', () => {
  const result = validateLockfileRegistry({
    packages: {
      '': { name: 'seller-ai-copilot-frontend' },
      'node_modules/a': {
        resolved: `https://${ALLOWED_REGISTRY_HOST}/a/-/a-1.0.0.tgz`,
      },
      'node_modules/b': {
        resolved: `https://${ALLOWED_REGISTRY_HOST}/b/-/b-1.0.0.tgz`,
      },
    },
  });

  assert.equal(result.checked, 2);
  assert.equal(result.violations.length, 0);
});

test('validates the repository lockfile with the expected checked count', () => {
  const lockfile = JSON.parse(readFileSync(defaultLockfilePath(), 'utf8'));
  const result = validateLockfileRegistry(lockfile);
  assert.equal(result.violations.length, 0);
  assert.equal(result.checked, 651);
});

test('CLI validates the repository lockfile from another working directory', () => {
  const result = spawnSync(process.execPath, [validatorScript], {
    cwd: '/',
    encoding: 'utf8',
  });

  assert.equal(result.status, 0);
  assert.match(result.stdout, /Validated 651 package-lock resolved entries/);
});

test('CLI exits with code 1 for missing lockfiles without leaking home paths', () => {
  const result = spawnSync(process.execPath, [validatorScript, '/tmp/does-not-exist-package-lock.json'], {
    encoding: 'utf8',
  });

  assert.equal(result.status, 1);
  assert.match(result.stderr, /lockfile-not-found/);
  assert.doesNotMatch(result.stderr, /Users\//);
  assert.doesNotMatch(result.stderr, /HOME/);
});

test('importing the module does not execute the CLI', () => {
  assert.equal(typeof classifyResolvedSource, 'function');
  assert.equal(typeof defaultLockfilePath, 'function');
});
