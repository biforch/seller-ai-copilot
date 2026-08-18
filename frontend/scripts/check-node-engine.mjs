// Secondary install guard: npm lifecycle preinstall runs after npm begins reify.
// Primary toolchain gate is the explicit validator before npm ci in CI/Docker.
import { validateToolchain, formatFailure } from './validate-node-toolchain.mjs';

const result = validateToolchain();
if (!result.ok) {
  console.error(formatFailure(result));
  process.exit(1);
}
