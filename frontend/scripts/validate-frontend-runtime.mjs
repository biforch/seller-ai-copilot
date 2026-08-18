#!/usr/bin/env node
import { spawn } from 'node:child_process';
import { constants as fsConstants, accessSync } from 'node:fs';
import { access, lstat, stat } from 'node:fs/promises';
import { createRequire } from 'node:module';
import { dirname, join } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

export const EXPECTED_NODE_VERSION = 'v24.19.0';
export const SUCCESS_MESSAGE = 'frontend runtime environment validation passed';
export const SMOKE_SUCCESS_MESSAGE = 'frontend standalone runtime smoke passed';

export const NODE_GLOBAL_MODULE_ROOT = '/usr/local/lib/node_modules';
export const NODE_GLOBAL_NPM_DIR = '/usr/local/lib/node_modules/npm';
export const NODE_GLOBAL_COREPACK_DIR = '/usr/local/lib/node_modules/corepack';
export const NODE_GLOBAL_BIN_DIR = '/usr/local/bin';

export const FORBIDDEN_BINARIES = Object.freeze([
  'npm',
  'npx',
  'corepack',
  'yarn',
  'yarnpkg',
  'pnpm',
  'pnpx',
]);

export const REQUIRED_RUNTIME_MODULES = Object.freeze([
  'next/package.json',
  'react/package.json',
  'react-dom/package.json',
]);

const CANARY_SECRET = 'CANARY_FRONTEND_RUNTIME_VALIDATOR_SECRET';
const MAX_OUTPUT_CHARS = 120;
const MAX_SMOKE_IO_BYTES = 8192;
const DEFAULT_SMOKE_HOST = '127.0.0.1';
const DEFAULT_SMOKE_PORT = 3000;
const DEFAULT_SMOKE_TIMEOUT_MS = 30000;

export class RuntimeValidationError extends Error {
  constructor(reasonCode) {
    super(reasonCode);
    this.name = 'RuntimeValidationError';
    this.reasonCode = reasonCode;
  }
}

function defaultProjectRoot() {
  return join(dirname(fileURLToPath(import.meta.url)), '..');
}

function truncateOutput(value) {
  const text = String(value ?? '');
  if (text.length <= MAX_OUTPUT_CHARS) {
    return text;
  }
  return text.slice(0, MAX_OUTPUT_CHARS);
}

async function defaultPathAccessible(targetPath, mode = fsConstants.F_OK) {
  try {
    await access(targetPath, mode);
    return true;
  } catch {
    return false;
  }
}

async function defaultPathIsSymlink(targetPath) {
  try {
    const info = await lstat(targetPath);
    return info.isSymbolicLink();
  } catch {
    return false;
  }
}

function defaultCommandExists(commandName, pathValue = process.env.PATH ?? '') {
  for (const directory of pathValue.split(':').filter(Boolean)) {
    const candidate = join(directory, commandName);
    try {
      accessSync(candidate, fsConstants.X_OK);
      return true;
    } catch {
      // continue probing PATH entries
    }
  }
  return false;
}

function defaultResolveModule(moduleName, projectRoot) {
  const requireFromRoot = createRequire(pathToFileURL(join(projectRoot, 'package.json')).href);
  return requireFromRoot.resolve(moduleName);
}

export async function validateFrontendRuntime(options = {}) {
  const projectRoot = options.projectRoot ?? defaultProjectRoot();
  const nodeVersion = options.nodeVersion ?? process.version;
  const pathAccessible = options.pathAccessible ?? defaultPathAccessible;
  const pathIsSymlink = options.pathIsSymlink ?? defaultPathIsSymlink;
  const commandExists = options.commandExists ?? defaultCommandExists;
  const resolveModule = options.resolveModule ?? defaultResolveModule;

  if (nodeVersion !== EXPECTED_NODE_VERSION) {
    throw new RuntimeValidationError('NODE_VERSION_MISMATCH');
  }

  for (const commandName of FORBIDDEN_BINARIES) {
    let exists = false;
    try {
      exists = commandExists(commandName, options.pathValue);
    } catch {
      throw new RuntimeValidationError('FORBIDDEN_COMMAND_PROBE_FAILED');
    }
    if (exists) {
      throw new RuntimeValidationError(`FORBIDDEN_COMMAND_PRESENT:${commandName}`);
    }
  }

  for (const targetPath of [NODE_GLOBAL_NPM_DIR, NODE_GLOBAL_COREPACK_DIR]) {
    let present = false;
    try {
      present = await pathAccessible(targetPath);
    } catch {
      throw new RuntimeValidationError('FORBIDDEN_PATH_PROBE_FAILED');
    }
    if (present) {
      throw new RuntimeValidationError(`FORBIDDEN_PATH_PRESENT:${targetPath.split('/').at(-1)}`);
    }
  }

  for (const commandName of FORBIDDEN_BINARIES) {
    const shimPath = join(NODE_GLOBAL_BIN_DIR, commandName);
    let present = false;
    try {
      present =
        (await pathAccessible(shimPath)) || (await pathIsSymlink(shimPath));
    } catch {
      throw new RuntimeValidationError('FORBIDDEN_SHIM_PROBE_FAILED');
    }
    if (present) {
      throw new RuntimeValidationError(`FORBIDDEN_SHIM_PRESENT:${commandName}`);
    }
  }

  const serverPath = join(projectRoot, 'server.js');
  try {
    const serverInfo = await stat(serverPath);
    if (!serverInfo.isFile()) {
      throw new RuntimeValidationError('REQUIRED_SERVER_JS_MISSING');
    }
  } catch (error) {
    if (error instanceof RuntimeValidationError) {
      throw error;
    }
    throw new RuntimeValidationError('REQUIRED_SERVER_JS_MISSING');
  }

  const staticDir = join(projectRoot, '.next', 'static');
  try {
    const staticInfo = await stat(staticDir);
    if (!staticInfo.isDirectory()) {
      throw new RuntimeValidationError('REQUIRED_STATIC_DIR_MISSING');
    }
  } catch (error) {
    if (error instanceof RuntimeValidationError) {
      throw error;
    }
    throw new RuntimeValidationError('REQUIRED_STATIC_DIR_MISSING');
  }

  for (const moduleName of REQUIRED_RUNTIME_MODULES) {
    try {
      resolveModule(moduleName, projectRoot);
    } catch {
      throw new RuntimeValidationError(`REQUIRED_MODULE_MISSING:${moduleName.split('/')[0]}`);
    }
  }
}

function sleep(ms) {
  return new Promise((resolve) => {
    setTimeout(resolve, ms);
  });
}

async function waitForSmokeResponse(fetchImpl, url, deadlineMs) {
  while (Date.now() < deadlineMs) {
    try {
      const response = await fetchImpl(url, { signal: AbortSignal.timeout(1500) });
      if (response.status >= 200 && response.status < 500) {
        return { ok: true };
      }
      return { ok: false, reason: `SMOKE_HTTP_STATUS_${response.status}` };
    } catch {
      await sleep(200);
    }
  }
  return { ok: false, reason: 'SMOKE_HTTP_TIMEOUT' };
}

async function terminateChild(child, signalGraceMs = 500) {
  if (child.exitCode !== null || child.signalCode !== null) {
    return;
  }
  child.kill('SIGTERM');
  await sleep(signalGraceMs);
  if (child.exitCode === null && child.signalCode === null) {
    child.kill('SIGKILL');
  }
}

export async function runStandaloneSmoke(options = {}) {
  const projectRoot = options.projectRoot ?? defaultProjectRoot();
  const host = options.host ?? DEFAULT_SMOKE_HOST;
  const port = options.port ?? DEFAULT_SMOKE_PORT;
  const timeoutMs = options.timeoutMs ?? DEFAULT_SMOKE_TIMEOUT_MS;
  const spawnImpl = options.spawnImpl ?? spawn;
  const fetchImpl = options.fetchImpl ?? globalThis.fetch;

  if (typeof fetchImpl !== 'function') {
    throw new RuntimeValidationError('SMOKE_FETCH_UNAVAILABLE');
  }

  const env = {
    NODE_ENV: 'production',
    HOSTNAME: '0.0.0.0',
    PORT: String(port),
    PATH: '/usr/local/bin:/usr/bin:/bin',
  };

  const child = spawnImpl(process.execPath, ['server.js'], {
    cwd: projectRoot,
    env,
    stdio: ['ignore', 'pipe', 'pipe'],
    shell: false,
  });

  let capturedBytes = 0;
  const trackOutput = (chunk) => {
    capturedBytes += Buffer.byteLength(chunk);
    if (capturedBytes > MAX_SMOKE_IO_BYTES) {
      child.stdout?.destroy();
      child.stderr?.destroy();
    }
  };
  child.stdout?.on('data', trackOutput);
  child.stderr?.on('data', trackOutput);

  try {
    const result = await waitForSmokeResponse(
      fetchImpl,
      `http://${host}:${port}/login`,
      Date.now() + timeoutMs,
    );
    if (!result.ok) {
      throw new RuntimeValidationError(result.reason);
    }
  } finally {
    await terminateChild(child);
  }
}

export async function main(argv = process.argv.slice(2), options = {}) {
  const smokeMode = argv.includes('--smoke');
  try {
    if (smokeMode) {
      await runStandaloneSmoke(options.smokeOptions ?? {});
      console.log(SMOKE_SUCCESS_MESSAGE);
      return 0;
    }
    await validateFrontendRuntime(options.runtimeOptions ?? {});
    console.log(SUCCESS_MESSAGE);
    return 0;
  } catch (error) {
    if (error instanceof RuntimeValidationError) {
      console.error(truncateOutput(error.reasonCode));
      return 1;
    }
    console.error('FRONTEND_RUNTIME_VALIDATION_FAILED');
    return 1;
  }
}

export { CANARY_SECRET, defaultProjectRoot };

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  main().then((code) => {
    process.exitCode = code;
  });
}
