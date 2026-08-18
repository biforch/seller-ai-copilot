#!/usr/bin/env node
import { spawnSync } from 'node:child_process';
import { dirname, join } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

// Exact runtime contract for reproducible CI/Docker/local gates.
// package.json engines express compatible ranges; this validator pins the repo toolchain.
export const EXPECTED_NODE_VERSION = 'v24.19.0';
export const EXPECTED_NPM_VERSION = '11.17.0';
export const SEMVER_PATTERN = /^\d+\.\d+\.\d+(?:[-+][\w.-]+)?$/;

export function defaultProjectRoot() {
  return join(dirname(fileURLToPath(import.meta.url)), '..');
}

export function resolveBundledNpmPath(nodeExecPath = process.execPath) {
  const npmName = process.platform === 'win32' ? 'npm.cmd' : 'npm';
  return join(dirname(nodeExecPath), npmName);
}

export function parseNpmVersionOutput(output) {
  if (output === undefined || output === null) {
    return { ok: false, reason: 'npm-version-empty' };
  }
  if (typeof output !== 'string') {
    return { ok: false, reason: 'npm-version-malformed' };
  }

  const trimmed = output.trim();
  if (trimmed.length === 0) {
    return { ok: false, reason: 'npm-version-empty' };
  }

  const lines = trimmed.split(/\r?\n/);
  if (lines.length !== 1) {
    return { ok: false, reason: 'npm-version-multiline' };
  }

  const version = lines[0];
  if (!SEMVER_PATTERN.test(version)) {
    return { ok: false, reason: 'npm-version-malformed' };
  }

  return { ok: true, version };
}

export function evaluateNodeVersion(actual, expected = EXPECTED_NODE_VERSION) {
  if (actual !== expected) {
    return {
      ok: false,
      reason: 'node-version-mismatch',
      actual,
      expected,
    };
  }
  return { ok: true, version: actual };
}

export function evaluateNpmVersion(actual, expected = EXPECTED_NPM_VERSION) {
  if (actual !== expected) {
    return {
      ok: false,
      reason: 'npm-version-mismatch',
      actual,
      expected,
    };
  }
  return { ok: true, version: actual };
}

export function detectNpmVersion(options = {}) {
  const {
    npmPath = resolveBundledNpmPath(options.nodeExecPath),
    spawnImpl = spawnSync,
    timeoutMs = 5000,
    maxOutputBytes = 4096,
    env = process.env,
  } = options;

  let result;
  try {
    result = spawnImpl(npmPath, ['--version'], {
      encoding: 'utf8',
      timeout: timeoutMs,
      maxBuffer: maxOutputBytes,
      shell: false,
      env,
    });
  } catch (error) {
    if (error && typeof error === 'object' && 'code' in error && error.code === 'ETIMEDOUT') {
      return { ok: false, reason: 'npm-command-timeout' };
    }
    return { ok: false, reason: 'npm-command-failed' };
  }

  if (result.error) {
    if (result.error.code === 'ETIMEDOUT') {
      return { ok: false, reason: 'npm-command-timeout' };
    }
    return { ok: false, reason: 'npm-command-failed' };
  }

  if (result.signal) {
    return { ok: false, reason: 'npm-command-failed' };
  }

  if (result.status !== 0) {
    return { ok: false, reason: 'npm-command-nonzero' };
  }

  const stdoutBytes = Buffer.byteLength(result.stdout ?? '', 'utf8');
  const stderrBytes = Buffer.byteLength(result.stderr ?? '', 'utf8');
  if (stdoutBytes + stderrBytes > maxOutputBytes) {
    return { ok: false, reason: 'npm-output-oversized' };
  }

  const parsed = parseNpmVersionOutput(result.stdout ?? '');
  if (!parsed.ok) {
    return parsed;
  }

  return evaluateNpmVersion(parsed.version);
}

export function validateToolchain(options = {}) {
  const nodeVersion = options.nodeVersion ?? process.version;
  const nodeEval = evaluateNodeVersion(nodeVersion, options.expectedNodeVersion);
  if (!nodeEval.ok) {
    return nodeEval;
  }

  const npmEval = detectNpmVersion(options);
  if (!npmEval.ok) {
    return npmEval;
  }

  return {
    ok: true,
    nodeVersion,
    npmVersion: npmEval.version,
  };
}

export function formatFailure(result) {
  if (result.reason === 'node-version-mismatch' || result.reason === 'npm-version-mismatch') {
    return `error: ${result.reason} expected=${result.expected} actual=${result.actual}`;
  }
  return `error: ${result.reason}`;
}

export function main() {
  const result = validateToolchain();
  if (!result.ok) {
    console.error(formatFailure(result));
    process.exit(1);
  }
  console.log(`toolchain-ok node=${result.nodeVersion} npm=${result.npmVersion}`);
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  main();
}
