import { readdir, readFile, stat } from 'node:fs/promises';
import path from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

const scriptDir = path.dirname(fileURLToPath(import.meta.url));
const frontendRoot = path.join(scriptDir, '..');

const SOURCE_ROOTS = ['app', 'components', 'hooks', 'lib'];
const SOURCE_FILE_PATTERN = /\.(ts|tsx|js|jsx)$/u;
const IGNORED_SEGMENTS = ['node_modules', '.next', 'dist'];

const FORBIDDEN_PATTERNS = [
  { id: 'localStorage access_token', pattern: /localStorage[\s\S]{0,80}access_token/u },
  { id: 'Authorization: Bearer', pattern: /Authorization[\s\S]{0,24}Bearer/u },
  { id: 'LoginResponse access_token', pattern: /LoginResponse[\s\S]{0,120}access_token/u },
];

export async function collectSourceFiles(rootDir) {
  const files = [];
  async function walk(currentDir) {
    const entries = await readdir(currentDir, { withFileTypes: true });
    for (const entry of entries) {
      if (IGNORED_SEGMENTS.includes(entry.name)) {
        continue;
      }
      const fullPath = path.join(currentDir, entry.name);
      if (entry.isDirectory()) {
        await walk(fullPath);
        continue;
      }
      if (!SOURCE_FILE_PATTERN.test(entry.name) || entry.name.endsWith('.test.ts') || entry.name.endsWith('.test.tsx')) {
        continue;
      }
      files.push(fullPath);
    }
  }

  for (const relativeRoot of SOURCE_ROOTS) {
    const absoluteRoot = path.join(rootDir, relativeRoot);
    try {
      const rootStat = await stat(absoluteRoot);
      if (rootStat.isDirectory()) {
        await walk(absoluteRoot);
      }
    } catch {
      // Ignore missing roots in isolated fixtures.
    }
  }

  return files.sort();
}

export async function validateCookieAuthContract(options = {}) {
  const rootDir = options.rootDir ?? frontendRoot;
  const files = await collectSourceFiles(rootDir);
  const violations = [];

  for (const filePath of files) {
    const source = await readFile(filePath, 'utf8');
    for (const rule of FORBIDDEN_PATTERNS) {
      if (rule.pattern.test(source)) {
        violations.push(`${path.relative(rootDir, filePath)}: ${rule.id}`);
      }
    }
  }

  if (violations.length > 0) {
    throw new Error(violations.join('\n'));
  }
}

export async function main() {
  try {
    await validateCookieAuthContract();
    console.log('COOKIE_AUTH_CONTRACT_OK');
    return 0;
  } catch (error) {
    console.error(error instanceof Error ? error.message : String(error));
    return 1;
  }
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  process.exitCode = await main();
}
