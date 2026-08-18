#!/usr/bin/env node
import { readFileSync } from 'node:fs';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

export const ALLOWED_REGISTRY_HOST = 'registry.npmjs.org';
export const ALLOWED_REGISTRY_ORIGIN = `https://${ALLOWED_REGISTRY_HOST}/`;

const UNSAFE_SOURCE_PATTERNS = [
  /^git\+/i,
  /^github:/i,
  /^file:/i,
  /^workspace:/i,
];

const CONTROL_CHAR_PATTERN = /[\u0000-\u001F\u007F]/;

export function defaultLockfilePath() {
  return join(dirname(fileURLToPath(import.meta.url)), '..', 'package-lock.json');
}

export function parseLockfile(jsonText) {
  return JSON.parse(jsonText);
}

export function classifyResolvedSource(resolved) {
  if (typeof resolved !== 'string') {
    return { ok: false, reason: 'non-string-resolved' };
  }

  if (resolved.length === 0) {
    return { ok: false, reason: 'missing-or-empty-resolved' };
  }

  if (CONTROL_CHAR_PATTERN.test(resolved)) {
    return { ok: false, reason: 'control-character' };
  }

  if (resolved.trim() !== resolved) {
    return { ok: false, reason: 'non-canonical-resolved' };
  }

  for (const pattern of UNSAFE_SOURCE_PATTERNS) {
    if (pattern.test(resolved)) {
      return { ok: false, reason: pattern.source.replace(/[\^$]/g, '') };
    }
  }

  if (resolved.startsWith('//')) {
    return { ok: false, reason: 'protocol-relative-url' };
  }

  if (resolved.startsWith('http://')) {
    return { ok: false, reason: 'http-protocol' };
  }

  let url;
  try {
    url = new URL(resolved);
  } catch {
    return { ok: false, reason: 'malformed-url' };
  }

  if (url.protocol !== 'https:') {
    return { ok: false, reason: 'non-https-protocol' };
  }

  if (url.username || url.password) {
    return { ok: false, reason: 'url-userinfo' };
  }

  if (url.hostname !== ALLOWED_REGISTRY_HOST) {
    return { ok: false, reason: 'disallowed-host' };
  }

  if (url.port !== '') {
    return { ok: false, reason: 'non-default-port' };
  }

  if (url.search !== '') {
    return { ok: false, reason: 'url-query' };
  }

  if (url.hash !== '') {
    return { ok: false, reason: 'url-fragment' };
  }

  if (!url.pathname.startsWith('/') || url.pathname.includes('\\')) {
    return { ok: false, reason: 'invalid-pathname' };
  }

  return { ok: true, reason: null };
}

export function validateLockfileRegistry(lockfile, { allowMissingResolvedFor = new Set(['']) } = {}) {
  const packages = lockfile?.packages;
  if (!packages || typeof packages !== 'object') {
    throw new Error('invalid-lockfile-structure');
  }

  const violations = [];
  let checked = 0;

  for (const [packagePath, meta] of Object.entries(packages)) {
    if (!meta || typeof meta !== 'object') {
      continue;
    }

    const resolved = meta.resolved;
    if (resolved === undefined) {
      if (allowMissingResolvedFor.has(packagePath)) {
        continue;
      }
      violations.push({ packagePath, reason: 'missing-resolved' });
      continue;
    }

    checked += 1;
    const verdict = classifyResolvedSource(resolved);
    if (!verdict.ok) {
      violations.push({ packagePath, reason: verdict.reason });
    }
  }

  return { checked, violations };
}

export function formatViolationMessage(violation) {
  return `${violation.packagePath}: ${violation.reason}`;
}

export function validateLockfileFile(lockfilePath = defaultLockfilePath()) {
  const absolutePath = resolve(lockfilePath);
  let jsonText;
  try {
    jsonText = readFileSync(absolutePath, 'utf8');
  } catch (error) {
    if (error && typeof error === 'object' && 'code' in error && error.code === 'ENOENT') {
      throw new Error('lockfile-not-found');
    }
    throw new Error('lockfile-read-failed');
  }

  let lockfile;
  try {
    lockfile = parseLockfile(jsonText);
  } catch {
    throw new Error('lockfile-parse-failed');
  }

  return validateLockfileRegistry(lockfile);
}

export function main(argv = process.argv.slice(2)) {
  try {
    const lockfilePath = argv[0] ? resolve(argv[0]) : defaultLockfilePath();
    const { checked, violations } = validateLockfileFile(lockfilePath);

    if (violations.length > 0) {
      for (const violation of violations) {
        console.error(formatViolationMessage(violation));
      }
      process.exit(1);
    }

    console.log(`Validated ${checked} package-lock resolved entries against ${ALLOWED_REGISTRY_ORIGIN}`);
  } catch (error) {
    const reason = error instanceof Error ? error.message : 'validation-failed';
    console.error(reason);
    process.exit(1);
  }
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  main();
}
