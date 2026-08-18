const major = Number(process.versions.node.split(".")[0], 10);

if (major !== 24) {
  console.error("error: Node.js 24.x is required (see .nvmrc and package.json engines)");
  process.exit(1);
}
