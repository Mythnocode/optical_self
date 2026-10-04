"""Build gate: verify the copied package contents before producing an installer."""
import hashlib
import importlib.metadata as metadata
import json
from pathlib import Path
import site
import sys

root = Path(sys.argv[1]).resolve()
manifest = json.loads((root / 'resources-manifest.json').read_text(encoding='utf-8'))
if Path(sys.executable).resolve() != (root / 'python/python.exe').resolve():
    raise RuntimeError('Run this gate with the bundled Python executable.')
if not sys.flags.isolated or not sys.flags.no_user_site or site.ENABLE_USER_SITE:
    raise RuntimeError('Packaged Python is not isolated from the user environment.')
if not sys.flags.utf8_mode:
    raise RuntimeError('Launch the bundled Python with -X utf8 for Chinese logs and text files.')
for entry in manifest['files']:
    path = root / entry['path']
    if not path.is_file() or path.stat().st_size != entry['bytes']:
        raise RuntimeError(f'Missing or incomplete packaged resource: {entry["path"]}')
    with path.open('rb') as stream:
        if hashlib.file_digest(stream, 'sha256').hexdigest() != entry['sha256']:
            raise RuntimeError(f'Packaged resource checksum differs: {entry["path"]}')
for name, version in manifest['packages'].items():
    if metadata.version(name) != version:
        raise RuntimeError(f'Packaged dependency version differs: {name}')
import numpy, scipy, pandas, sklearn, xgboost, torch, shap, matplotlib  # noqa: E401
import fastapi, uvicorn, httpx, websockets, openpyxl, yaml  # noqa: E401
from optical_core.physics.geometric.solvers.native_trace import native_available
if not native_available():
    raise RuntimeError('The packaged C++ trace kernel cannot be loaded.')
# Ensure the process actually used the app-local C++ runtime, rather than a
# Visual C++ installation on the build machine masking missing dependencies.
import ctypes
from ctypes import wintypes
modules = (wintypes.HMODULE * 2048)()
needed = wintypes.DWORD()
ctypes.windll.kernel32.GetCurrentProcess.restype = wintypes.HANDLE
ctypes.windll.psapi.EnumProcessModules.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.HMODULE), wintypes.DWORD, ctypes.POINTER(wintypes.DWORD)]
ctypes.windll.psapi.EnumProcessModules.restype = wintypes.BOOL
ctypes.windll.psapi.GetModuleFileNameExW.argtypes = [wintypes.HANDLE, wintypes.HMODULE, wintypes.LPWSTR, wintypes.DWORD]
ctypes.windll.psapi.GetModuleFileNameExW.restype = wintypes.DWORD
process = ctypes.windll.kernel32.GetCurrentProcess()
if not ctypes.windll.psapi.EnumProcessModules(process, modules, ctypes.sizeof(modules), ctypes.byref(needed)):
    raise RuntimeError('Cannot inspect loaded runtime DLLs.')
loaded = {}
loaded_native = None
runtime_names = {name.lower() for name in manifest['vc_runtime']['dlls']}
for module in modules[:needed.value // ctypes.sizeof(wintypes.HMODULE)]:
    buffer = ctypes.create_unicode_buffer(32768)
    ctypes.windll.psapi.GetModuleFileNameExW(process, module, buffer, len(buffer))
    path = Path(buffer.value)
    if path.name.lower() == 'optical_native.dll':
        if path.resolve() != (root / 'backend/native/build/optical_native.dll').resolve():
            raise RuntimeError(f'The optical native kernel escaped the bundle: {path}')
        loaded_native = str(path)
    if path.name.lower() in runtime_names:
        if not path.resolve().is_relative_to((root / 'python').resolve()):
            raise RuntimeError(f'C++ runtime escaped the bundle: {path}')
        # Some wheels load their own recorded, bundled copy by absolute path.
        # Keep all copies so a system DLL cannot be hidden by a later module.
        loaded.setdefault(path.name.lower(), []).append(str(path))
if 'msvcp140.dll' not in loaded:
    raise RuntimeError('The app-local Microsoft C++ runtime was not loaded.')
if loaded_native is None:
    raise RuntimeError('The bundled optical native kernel was not loaded.')
print(json.dumps({'python': sys.executable, 'isolated': True, 'utf8_mode': True, 'files': len(manifest['files']),
                  'packages': len(manifest['packages']), 'native_available': True,
                  'native_dll_sha256': manifest['native_dll_sha256'], 'loaded_native_dll': loaded_native,
                  'loaded_cpp_runtime': loaded}), flush=True)
