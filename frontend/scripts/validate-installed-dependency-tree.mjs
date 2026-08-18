#!/usr/bin/env node
import { spawnSync } from 'node:child_process';
import { existsSync, readdirSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

import { resolveBundledNpmPath } from './validate-node-toolchain.mjs';

export const DEFAULT_TIMEOUT_MS = 120_000;
export const DEFAULT_MAX_OUTPUT_BYTES = 16 * 1024 * 1024;
export const DEFAULT_MAX_TREE_DEPTH = 64;
export const DEFAULT_MAX_TREE_NODES = 50_000;
export const DEFAULT_MAX_FIELD_LENGTH = 256;

export function defaultProjectRoot() {
  return join(dirname(fileURLToPath(import.meta.url)), '..');
}

export function nodeModulesInstalled(cwd) {
  const nodeModulesPath = join(cwd, 'node_modules');
  if (!existsSync(nodeModulesPath)) {
    return false;
  }
  try {
    const entries = readdirSync(nodeModulesPath).filter((entry) => !entry.startsWith('.'));
    return entries.length > 0;
  } catch {
    return false;
  }
}

export function parseJsonOutput(text, schemaLabel) {
  if (typeof text !== 'string' || text.trim().length === 0) {
    throw new Error(`${schemaLabel}-empty`);
  }

  let parsed;
  try {
    parsed = JSON.parse(text);
  } catch {
    throw new Error(`${schemaLabel}-malformed`);
  }

  return parsed;
}

export function parseExtraneousQuery(json) {
  if (!Array.isArray(json)) {
    throw new Error('extraneous-schema-invalid');
  }

  return json.map((item) => {
    if (!item || typeof item !== 'object') {
      throw new Error('extraneous-schema-invalid');
    }
    if (typeof item.name !== 'string' || typeof item.version !== 'string') {
      throw new Error('extraneous-schema-invalid');
    }
    return { name: item.name, version: item.version };
  });
}

export function countDependencyProblems(problems) {
  if (problems === undefined) {
    return { invalid: 0, unmet: 0 };
  }
  if (!Array.isArray(problems)) {
    throw new Error('npm-ls-schema-invalid');
  }

  let invalid = 0;
  let unmet = 0;
  for (const problem of problems) {
    if (typeof problem !== 'string') {
      throw new Error('npm-ls-schema-invalid');
    }
    const lower = problem.toLowerCase();
    if (lower.includes('invalid')) {
      invalid += 1;
    }
    if (lower.includes('unmet') || lower.includes('missing')) {
      unmet += 1;
    }
  }

  return { invalid, unmet };
}

export function scanDependencyTree(
  node,
  state = { nodes: 0, extraneous: 0, invalid: 0, unmet: 0 },
  depth = 0,
  limits = {},
) {
  const maxDepth = limits.maxDepth ?? DEFAULT_MAX_TREE_DEPTH;
  const maxNodes = limits.maxNodes ?? DEFAULT_MAX_TREE_NODES;
  const maxFieldLength = limits.maxFieldLength ?? DEFAULT_MAX_FIELD_LENGTH;

  if (depth > maxDepth) {
    throw new Error('npm-ls-tree-limit-exceeded');
  }
  if (state.nodes >= maxNodes) {
    throw new Error('npm-ls-tree-limit-exceeded');
  }
  if (!node || typeof node !== 'object' || Array.isArray(node)) {
    return state;
  }

  state.nodes += 1;

  for (const field of ['name', 'version']) {
    const value = node[field];
    if (typeof value === 'string' && value.length > maxFieldLength) {
      throw new Error('npm-ls-tree-limit-exceeded');
    }
  }

  if (node.extraneous === true) {
    state.extraneous += 1;
  }
  if (node.invalid === true || node.invalid === 'true') {
    state.invalid += 1;
  }
  if (node.missing === true || node.missing === 'true') {
    state.unmet += 1;
  }

  const dependencies = node.dependencies;
  if (dependencies && typeof dependencies === 'object' && !Array.isArray(dependencies)) {
    for (const child of Object.values(dependencies)) {
      scanDependencyTree(child, state, depth + 1, limits);
    }
  }

  return state;
}

export function mergeInstalledTreeCounts(queryExtraneous, problemCounts, treeCounts) {
  return {
    extraneousCount: Math.max(queryExtraneous, treeCounts.extraneous),
    invalidCount: Math.max(problemCounts.invalid, treeCounts.invalid),
    unmetCount: Math.max(problemCounts.unmet, treeCounts.unmet),
  };
}

export function evaluateInstalledTree({ extraneousCount, invalidCount, unmetCount }) {
  if (extraneousCount > 0) {
    return {
      ok: false,
      reason: 'extraneous-packages',
      extraneousCount,
      invalidCount,
      unmetCount,
    };
  }
  if (invalidCount > 0) {
    return {
      ok: false,
      reason: 'invalid-dependencies',
      extraneousCount,
      invalidCount,
      unmetCount,
    };
  }
  if (unmetCount > 0) {
    return {
      ok: false,
      reason: 'unmet-dependencies',
      extraneousCount,
      invalidCount,
      unmetCount,
    };
  }

  return {
    ok: true,
    extraneousCount: 0,
    invalidCount: 0,
    unmetCount: 0,
  };
}

export function runNpmJson(args, options = {}) {
  const {
    cwd,
    npmPath = resolveBundledNpmPath(options.nodeExecPath),
    spawnImpl = spawnSync,
    timeoutMs = DEFAULT_TIMEOUT_MS,
    maxOutputBytes = DEFAULT_MAX_OUTPUT_BYTES,
    env = process.env,
  } = options;

  let result;
  try {
    result = spawnImpl(npmPath, args, {
      cwd,
      encoding: 'utf8',
      timeout: timeoutMs,
      maxBuffer: maxOutputBytes,
      shell: false,
      env,
    });
  } catch (error) {
    if (error && typeof error === 'object' && 'code' in error && error.code === 'ETIMEDOUT') {
      return { ok: false, reason: 'npm-command-timeout', stdout: '', stderr: '' };
    }
    return { ok: false, reason: 'npm-command-failed', stdout: '', stderr: '' };
  }

  if (result.error) {
    if (result.error.code === 'ETIMEDOUT') {
      return { ok: false, reason: 'npm-command-timeout', stdout: result.stdout ?? '', stderr: result.stderr ?? '' };
    }
    return { ok: false, reason: 'npm-command-failed', stdout: result.stdout ?? '', stderr: result.stderr ?? '' };
  }

  if (result.signal) {
    return { ok: false, reason: 'npm-command-failed', stdout: result.stdout ?? '', stderr: result.stderr ?? '' };
  }

  const stdout = result.stdout ?? '';
  const stderr = result.stderr ?? '';
  const outputBytes = Buffer.byteLength(stdout, 'utf8') + Buffer.byteLength(stderr, 'utf8');
  if (outputBytes > maxOutputBytes) {
    return { ok: false, reason: 'npm-output-oversized', stdout, stderr };
  }

  return {
    ok: true,
    status: result.status ?? 1,
    stdout,
    stderr,
  };
}

export function validateInstalledTree(options = {}) {
  const cwd = options.cwd ?? defaultProjectRoot();

  if (!nodeModulesInstalled(cwd)) {
    return { ok: false, reason: 'installed-tree-missing' };
  }

  const queryRun = runNpmJson(['query', ':extraneous', '--json'], { ...options, cwd });
  if (!queryRun.ok) {
    return { ok: false, reason: queryRun.reason };
  }

  let extraneous;
  try {
    extraneous = parseExtraneousQuery(parseJsonOutput(queryRun.stdout, 'extraneous-json'));
  } catch (error) {
    const reason = error instanceof Error ? error.message : 'extraneous-schema-invalid';
    return { ok: false, reason };
  }

  const lsRun = runNpmJson(['ls', '--all', '--json'], { ...options, cwd });
  if (!lsRun.ok) {
    return { ok: false, reason: lsRun.reason };
  }

  if (lsRun.stdout.trim().length === 0) {
    return { ok: false, reason: 'npm-ls-execution-failure' };
  }

  let tree;
  try {
    tree = parseJsonOutput(lsRun.stdout, 'npm-ls-json');
  } catch (error) {
    const reason = error instanceof Error ? error.message : 'npm-ls-malformed';
    return { ok: false, reason };
  }

  if (!tree || typeof tree !== 'object' || Array.isArray(tree)) {
    return { ok: false, reason: 'npm-ls-schema-invalid' };
  }

  let problemCounts;
  try {
    problemCounts = countDependencyProblems(tree.problems);
  } catch (error) {
    const reason = error instanceof Error ? error.message : 'npm-ls-schema-invalid';
    return { ok: false, reason };
  }

  let treeCounts;
  try {
    treeCounts = scanDependencyTree(tree, undefined, 0, options);
  } catch (error) {
    const reason = error instanceof Error ? error.message : 'npm-ls-tree-limit-exceeded';
    return { ok: false, reason };
  }

  return evaluateInstalledTree(
    mergeInstalledTreeCounts(extraneous.length, problemCounts, treeCounts),
  );
}

export function formatFailure(result) {
  if (
    result.reason === 'extraneous-packages'
    || result.reason === 'invalid-dependencies'
    || result.reason === 'unmet-dependencies'
  ) {
    return `error: ${result.reason} extraneous=${result.extraneousCount} invalid=${result.invalidCount} unmet=${result.unmetCount}`;
  }
  return `error: ${result.reason}`;
}

export function main() {
  const result = validateInstalledTree();
  if (!result.ok) {
    console.error(formatFailure(result));
    process.exit(1);
  }
  console.log(
    `installed-tree-ok extraneous=${result.extraneousCount} invalid=${result.invalidCount} unmet=${result.unmetCount}`,
  );
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  main();
}
