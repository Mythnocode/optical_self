import { spawn } from 'node:child_process';
import { resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const root = resolve(fileURLToPath(new URL('..', import.meta.url)));
function run(executable, args) {
  return new Promise((resolveRun, reject) => {
    const child = spawn(executable, args, { cwd: root, stdio: 'inherit', windowsHide: true });
    child.once('error', reject);
    child.once('exit', (code, signal) => code === 0 ? resolveRun() : reject(new Error(`${executable} exited: ${code ?? signal}`)));
  });
}
if (process.platform !== 'win32') throw new Error('The current optical native bundle targets Windows x64.');
const python = process.env.OPTICAL_PYTHON_EXECUTABLE || 'python';
await run(process.execPath, [resolve(root, 'scripts/build.mjs')]);
await run(python, [resolve(root, 'scripts/stage-desktop-runtime.py')]);
await run(process.execPath, [resolve(root, 'node_modules/electron-builder/cli.js'), '--win', '--x64',
  '--config', 'electron-builder.yml', '--publish', 'never', ...(process.argv.includes('--dir') ? ['--dir'] : [])]);
