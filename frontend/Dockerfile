FROM node:24-alpine@sha256:d32cdf619f63fe0471182d08996dd516c6275bb5fd31ae06e55a570bd9e1ad43

WORKDIR /app

COPY package.json package-lock.json .npmrc ./
COPY scripts/validate-node-toolchain.mjs ./scripts/validate-node-toolchain.mjs
COPY scripts/validate-lockfile-registry.mjs ./scripts/validate-lockfile-registry.mjs
COPY scripts/validate-installed-dependency-tree.mjs ./scripts/validate-installed-dependency-tree.mjs
COPY scripts/check-node-engine.mjs ./scripts/check-node-engine.mjs
RUN node scripts/validate-node-toolchain.mjs \
    && node scripts/validate-lockfile-registry.mjs \
    && npm ci \
    && node scripts/validate-installed-dependency-tree.mjs

COPY . .

EXPOSE 3000

CMD ["npm", "run", "dev"]
