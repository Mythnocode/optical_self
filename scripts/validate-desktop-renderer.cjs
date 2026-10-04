// Build gate: ensure the packaged renderer and desktop entry points are complete.
const { createHash } = require('node:crypto');
const { readFileSync, readdirSync, statSync } = require('node:fs');
const { join, normalize, relative, resolve } = require('node:path');
const { extractFile } = require('@electron/asar');

function validateRenderer(resources) {
  const root = resolve(__dirname, '..');
  const archive = join(resources, 'app.asar');
  const files = ['desktop-dist/main.cjs', 'desktop-dist/preload.cjs'];
  function collect(directory) {
    for (const name of readdirSync(directory)) {
      const path = join(directory, name);
      if (statSync(path).isDirectory()) collect(path);
      else if (!path.endsWith('.map')) files.push(relative(root, path).replaceAll('\\', '/'));
    }
  }
  collect(join(root, 'frontend_web/dist'));
  const checksum = (bytes) => createHash('sha256').update(bytes).digest('hex');
  for (const file of files) {
    if (checksum(readFileSync(join(root, file))) !== checksum(extractFile(archive, normalize(file)))) {
      throw new Error(`Packaged renderer file differs from the build: ${file}`);
    }
  }
  const report = { archive, files: files.length, sha256: checksum(readFileSync(archive)) };
  console.log(JSON.stringify(report));
  return report;
}
module.exports = validateRenderer;
if (require.main === module) validateRenderer(resolve(process.argv[2]));
