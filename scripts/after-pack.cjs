const { spawn } = require('node:child_process');
const { join, resolve } = require('node:path');

module.exports = async function afterPack(context) {
  const resources = join(context.appOutDir, 'resources');
  require('./validate-desktop-renderer.cjs')(resources);
  await new Promise((resolveProbe, reject) => {
    const probe = spawn(join(resources, 'python', 'python.exe'), ['-I', '-B', '-X', 'utf8',
      resolve(__dirname, 'validate-desktop-resources.py'), resources], {
      windowsHide: true, stdio: 'inherit',
      env: { ...process.env, OPTICAL_NATIVE: '1', OPTICAL_NATIVE_DLL: join(resources, 'backend', 'native', 'build', 'optical_native.dll'),
        MPLCONFIGDIR: resolve(__dirname, '../build/desktop-validation-cache/matplotlib'),
        NUMBA_CACHE_DIR: resolve(__dirname, '../build/desktop-validation-cache/numba') },
    });
    probe.once('error', reject);
    probe.once('exit', (code, signal) => code === 0 ? resolveProbe() : reject(new Error(`Packaged runtime validation failed: ${code ?? signal}`)));
  });
};
