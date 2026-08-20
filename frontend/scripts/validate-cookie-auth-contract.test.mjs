import assert from 'node:assert/strict';
import { mkdtemp, mkdir, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import test from 'node:test';

import { collectSourceFiles, validateCookieAuthContract } from './validate-cookie-auth-contract.mjs';

test('clean frontend passes cookie auth contract validation', async () => {
  await validateCookieAuthContract();
});

test('validator rejects localStorage access_token usage', async () => {
  const root = await mkdtemp(join(tmpdir(), 'cookie-auth-contract-'));
  await mkdir(join(root, 'lib'), { recursive: true });
  await writeFile(join(root, 'lib', 'bad.ts'), "localStorage.setItem('access_token', value);\n");
  await assert.rejects(
    () => validateCookieAuthContract({ rootDir: root }),
    /localStorage access_token/,
  );
});

test('validator rejects Authorization Bearer header construction', async () => {
  const root = await mkdtemp(join(tmpdir(), 'cookie-auth-contract-'));
  await mkdir(join(root, 'app'), { recursive: true });
  await writeFile(join(root, 'app', 'client.ts'), "headers.Authorization = `Bearer ${token}`;\n");
  await assert.rejects(
    () => validateCookieAuthContract({ rootDir: root }),
    /Authorization: Bearer/,
  );
});

test('collectSourceFiles skips test files', async () => {
  const root = await mkdtemp(join(tmpdir(), 'cookie-auth-contract-'));
  await mkdir(join(root, 'lib'), { recursive: true });
  await writeFile(join(root, 'lib', 'auth.test.ts'), "localStorage.setItem('access_token', 'x');\n");
  const files = await collectSourceFiles(root);
  assert.deepEqual(files, []);
});
