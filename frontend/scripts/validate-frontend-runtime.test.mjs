import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import { EventEmitter } from 'node:events';
import { mkdtemp, mkdir, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import test from 'node:test';

import {
  CANARY_SECRET,
  EXPECTED_NODE_VERSION,
  NODE_GLOBAL_COREPACK_DIR,
  NODE_GLOBAL_NPM_DIR,
  SUCCESS_MESSAGE,
  main,
  runStandaloneSmoke,
  validateFrontendRuntime,
} from './validate-frontend-runtime.mjs';

const scriptDir = dirname(fileURLToPath(import.meta.url));
const frontendRoot = join(scriptDir, '..');

async function createCleanProjectRoot() {
  const root = await mkdtemp(join(tmpdir(), 'frontend-runtime-'));
  await mkdir(join(root, '.next', 'static'), { recursive: true });
  await writeFile(join(root, 'server.js'), 'export {};\n');
  await writeFile(join(root, 'package.json'), '{"name":"runtime-test"}\n');
  await mkdir(join(root, 'node_modules', 'next'), { recursive: true });
  await mkdir(join(root, 'node_modules', 'react'), { recursive: true });
  await mkdir(join(root, 'node_modules', 'react-dom'), { recursive: true });
  await writeFile(join(root, 'node_modules', 'next', 'package.json'), '{}\n');
  await writeFile(join(root, 'node_modules', 'react', 'package.json'), '{}\n');
  await writeFile(join(root, 'node_modules', 'react-dom', 'package.json'), '{}\n');
  return root;
}

function cleanProbes(projectRoot, overrides = {}) {
  return {
    projectRoot,
    nodeVersion: EXPECTED_NODE_VERSION,
    pathAccessible: async () => false,
    pathIsSymlink: async () => false,
    commandExists: () => false,
    resolveModule: (moduleName) =>
      join(projectRoot, 'node_modules', moduleName.replace('/package.json', ''), 'package.json'),
    ...overrides,
  };
}

test('clean runtime passes', async () => {
  const projectRoot = await createCleanProjectRoot();
  await validateFrontendRuntime(cleanProbes(projectRoot));
});

test('npm present is rejected', async () => {
  const projectRoot = await createCleanProjectRoot();
  await assert.rejects(
    () =>
      validateFrontendRuntime(
        cleanProbes(projectRoot, {
          commandExists: (name) => name === 'npm',
        }),
      ),
    /FORBIDDEN_COMMAND_PRESENT:npm/,
  );
});

test('npx present is rejected', async () => {
  const projectRoot = await createCleanProjectRoot();
  await assert.rejects(
    () =>
      validateFrontendRuntime(
        cleanProbes(projectRoot, {
          commandExists: (name) => name === 'npx',
        }),
      ),
    /FORBIDDEN_COMMAND_PRESENT:npx/,
  );
});

test('corepack present is rejected', async () => {
  const projectRoot = await createCleanProjectRoot();
  await assert.rejects(
    () =>
      validateFrontendRuntime(
        cleanProbes(projectRoot, {
          commandExists: (name) => name === 'corepack',
        }),
      ),
    /FORBIDDEN_COMMAND_PRESENT:corepack/,
  );
});

test('yarn and pnpm shims present are rejected', async () => {
  const projectRoot = await createCleanProjectRoot();
  await assert.rejects(
    () =>
      validateFrontendRuntime(
        cleanProbes(projectRoot, {
          commandExists: (name) => name === 'pnpm' || name === 'yarn',
        }),
      ),
    /FORBIDDEN_COMMAND_PRESENT:(pnpm|yarn)/,
  );
});

test('global npm directory present is rejected', async () => {
  const projectRoot = await createCleanProjectRoot();
  await assert.rejects(
    () =>
      validateFrontendRuntime(
        cleanProbes(projectRoot, {
          pathAccessible: async (targetPath) => targetPath === NODE_GLOBAL_NPM_DIR,
        }),
      ),
    /FORBIDDEN_PATH_PRESENT:npm/,
  );
});

test('broken global shim symlink is rejected', async () => {
  const projectRoot = await createCleanProjectRoot();
  await assert.rejects(
    () =>
      validateFrontendRuntime(
        cleanProbes(projectRoot, {
          pathAccessible: async (targetPath) => targetPath === '/usr/local/bin/npm',
          pathIsSymlink: async (targetPath) => targetPath === '/usr/local/bin/npm',
        }),
      ),
    /FORBIDDEN_SHIM_PRESENT:npm/,
  );
});

test('node version mismatch is rejected', async () => {
  const projectRoot = await createCleanProjectRoot();
  await assert.rejects(
    () =>
      validateFrontendRuntime(
        cleanProbes(projectRoot, {
          nodeVersion: 'v24.0.0',
        }),
      ),
    /NODE_VERSION_MISMATCH/,
  );
});

test('missing server.js is rejected', async () => {
  const projectRoot = await createCleanProjectRoot();
  await assert.rejects(
    () =>
      validateFrontendRuntime(
        cleanProbes(projectRoot, {
          projectRoot: join(projectRoot, 'missing'),
        }),
      ),
    /REQUIRED_SERVER_JS_MISSING/,
  );
});

test('missing required runtime module is rejected', async () => {
  const projectRoot = await createCleanProjectRoot();
  await assert.rejects(
    () =>
      validateFrontendRuntime(
        cleanProbes(projectRoot, {
          resolveModule: (moduleName) => {
            if (moduleName.startsWith('react')) {
              throw new Error('missing');
            }
            return join(projectRoot, 'node_modules', 'next', 'package.json');
          },
        }),
      ),
    /REQUIRED_MODULE_MISSING:react/,
  );
});

test('probe exceptions fail closed', async () => {
  const projectRoot = await createCleanProjectRoot();
  await assert.rejects(
    () =>
      validateFrontendRuntime(
        cleanProbes(projectRoot, {
          commandExists: () => {
            throw new Error(CANARY_SECRET);
          },
        }),
      ),
    /FORBIDDEN_COMMAND_PROBE_FAILED/,
  );
});

test('main failure does not leak canary', async () => {
  const stderr = [];
  const originalError = console.error;
  console.error = (value) => {
    stderr.push(String(value));
  };
  try {
    const code = await main([], {
      runtimeOptions: {
        commandExists: () => {
          throw new Error(CANARY_SECRET);
        },
      },
    });
    assert.equal(code, 1);
    assert.equal(stderr.join('\n').includes(CANARY_SECRET), false);
    assert.equal(stderr.join('\n'), 'FORBIDDEN_COMMAND_PROBE_FAILED');
  } finally {
    console.error = originalError;
  }
});

test('main success prints short message without canary', async () => {
  const projectRoot = await createCleanProjectRoot();
  const logs = [];
  const originalLog = console.log;
  console.log = (value) => {
    logs.push(String(value));
  };
  try {
    const code = await main([], { runtimeOptions: cleanProbes(projectRoot) });
    assert.equal(code, 0);
    assert.equal(logs.join('\n'), SUCCESS_MESSAGE);
    assert.equal(logs.join('\n').includes(CANARY_SECRET), false);
  } finally {
    console.log = originalLog;
  }
});

test('standalone smoke succeeds with mock child and fetch', async () => {
  class MockChild extends EventEmitter {
    constructor() {
      super();
      this.exitCode = null;
      this.signalCode = null;
      this.stdout = new EventEmitter();
      this.stderr = new EventEmitter();
    }

    kill(signal) {
      this.signalCode = signal;
      this.emit('close');
    }
  }

  const projectRoot = await createCleanProjectRoot();
  await runStandaloneSmoke({
    projectRoot,
    spawnImpl: () => new MockChild(),
    fetchImpl: async () => ({ status: 200 }),
  });
});

test('global corepack directory present is rejected', async () => {
  const projectRoot = await createCleanProjectRoot();
  await assert.rejects(
    () =>
      validateFrontendRuntime(
        cleanProbes(projectRoot, {
          pathAccessible: async (targetPath) => targetPath === NODE_GLOBAL_COREPACK_DIR,
        }),
      ),
    /FORBIDDEN_PATH_PRESENT:corepack/,
  );
});

test('importing validator module does not execute main', async () => {
  const module = await import(`./validate-frontend-runtime.mjs?cacheBust=${Date.now()}`);
  assert.equal(typeof module.validateFrontendRuntime, 'function');
});

test('runtime node version contract is pinned to v24.19.0', () => {
  assert.equal(EXPECTED_NODE_VERSION, 'v24.19.0');
});

test('runtime node version contract matches frontend .nvmrc', async () => {
  const nvmrc = (await readFile(join(frontendRoot, '.nvmrc'), 'utf8')).trim();
  assert.equal(nvmrc, '24.19.0');
  assert.equal(EXPECTED_NODE_VERSION, `v${nvmrc}`);
});

test('runtime node version contract matches frontend package engines', async () => {
  const packageJson = JSON.parse(await readFile(join(frontendRoot, 'package.json'), 'utf8'));
  assert.match(packageJson.engines.node, /24\.19\.0/);
  assert.match(packageJson.engines.node, /<25/);
  assert.equal(packageJson.packageManager, 'npm@11.17.0');
});

test('runtime validator source is self-contained without cross-validator imports', async () => {
  const source = await readFile(join(scriptDir, 'validate-frontend-runtime.mjs'), 'utf8');
  assert.doesNotMatch(source, /validate-node-toolchain\.mjs/);
  assert.doesNotMatch(source, /validate-lockfile-registry\.mjs/);
  assert.doesNotMatch(source, /validate-installed-dependency-tree\.mjs/);
  assert.doesNotMatch(source, /from ['"]\.\/[^'"]+['"]/);
});

test('runtime validator works from isolated temp fixture without other frontend scripts', async () => {
  const projectRoot = await createCleanProjectRoot();
  await validateFrontendRuntime(cleanProbes(projectRoot));
});
