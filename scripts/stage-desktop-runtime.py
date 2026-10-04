"""Bundle the selected Windows Python interpreter and its locked runtime dependencies."""
from __future__ import annotations

import argparse
import hashlib
import importlib.metadata as metadata
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile

from packaging.requirements import Requirement
from packaging.utils import canonicalize_name

ROOT = Path(__file__).resolve().parents[1]
BUILD = (ROOT / 'build').resolve()
LOCK = ROOT / 'requirements/desktop-runtime.lock.txt'
ROOT_PACKAGES = ['numpy', 'scipy', 'pandas', 'matplotlib', 'openpyxl', 'scikit-learn',
                 'shap', 'xgboost', 'torch', 'joblib', 'cloudpickle', 'threadpoolctl',
                 'fastapi', 'uvicorn', 'websockets', 'httpx', 'pydantic', 'PyYAML']
SOURCE_DIRS = ['backend', 'machine_learning', 'optical_core', 'optical_runtime',
               'shared_contracts', 'shared_ports', 'shared_presentation',
               'teaching_runtime', 'help_runtime', 'resources', 'data_templates']


def dependencies():
    pending = [Requirement(name) for name in ROOT_PACKAGES]
    selected = {}
    seen = set()
    while pending:
        requirement = pending.pop()
        name = canonicalize_name(requirement.name)
        dist = metadata.distribution(name)
        if requirement.specifier and dist.version not in requirement.specifier:
            raise RuntimeError(f'{name}=={dist.version} does not satisfy {requirement}')
        selected[name] = dist
        extras = frozenset(requirement.extras)
        if (name, extras) in seen:
            continue
        seen.add((name, extras))
        for raw in dist.requires or []:
            dependency = Requirement(raw)
            if dependency.marker is None or any(dependency.marker.evaluate({'extra': extra}) for extra in extras | {''}):
                pending.append(dependency)
    return dict(sorted(selected.items()))


def inside_build(path):
    resolved = path.resolve()
    if resolved == BUILD or not resolved.is_relative_to(BUILD):
        raise RuntimeError(f'Generated output must remain below {BUILD}: {resolved}')
    return resolved


def ignore_generated(_directory, names):
    return set(names) & {'__pycache__', '.git', '.gitkeep', '.pytest_cache', '.mypy_cache', '.env'}


def hash_file(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def find_vc_runtime():
    explicit = os.environ.get('OPTICAL_VC_RUNTIME_DIR')
    if explicit:
        candidates = [Path(explicit).resolve()]
    else:
        visual_studio = Path(os.environ.get('ProgramFiles', 'C:/Program Files')) / 'Microsoft Visual Studio'
        candidates = sorted(visual_studio.glob('*/*/VC/Redist/MSVC/*/x64/Microsoft.VC143.CRT'),
                            key=lambda path: tuple(int(part) for part in path.parents[1].name.split('.')), reverse=True)
    required = {'msvcp140.dll', 'vcruntime140.dll', 'vcruntime140_1.dll', 'concrt140.dll'}
    for candidate in candidates:
        if all((candidate / name).is_file() for name in required):
            return candidate
    raise RuntimeError('Provide the Microsoft x64 redistributable DLL directory with OPTICAL_VC_RUNTIME_DIR, '
                       'or install the Visual Studio C++ redistributable build component.')


def stage(selected):
    if os.name != 'nt' or sys.version_info[:2] != (3, 12):
        raise RuntimeError('This bundle requires Windows x64 CPython 3.12.')
    if __import__('struct').calcsize('P') != 8:
        raise RuntimeError('The optical native DLL requires a 64-bit interpreter.')
    crt = find_vc_runtime()
    BUILD.mkdir(exist_ok=True)
    staging = inside_build(Path(tempfile.mkdtemp(prefix='desktop-resources-staging-', dir=BUILD)))
    output = inside_build(BUILD / 'desktop-resources')
    if output.exists() and not (output / 'resources-manifest.json').is_file():
        raise RuntimeError(f'Refusing to replace an unrecognized directory: {output}')
    runtime = staging / 'python'
    runtime.mkdir()
    prefix = Path(sys.base_prefix).resolve()
    for name in ['python.exe', 'pythonw.exe', 'python3.dll', 'python312.dll',
                 'vcruntime140.dll', 'vcruntime140_1.dll', 'LICENSE.txt']:
        shutil.copy2(prefix / name, runtime / name)
    for path in crt.glob('*.dll'):
        shutil.copy2(path, runtime / path.name)
    shutil.copytree(prefix / 'DLLs', runtime / 'DLLs', ignore=ignore_generated)
    shutil.copytree(prefix / 'Lib', runtime / 'Lib',
                    ignore=lambda directory, names: ignore_generated(directory, names) | (set(names) & {'site-packages'}))
    if (prefix / 'tcl').is_dir():
        shutil.copytree(prefix / 'tcl', runtime / 'tcl', ignore=ignore_generated)
    site_target = runtime / 'Lib/site-packages'
    site_target.mkdir()
    count = 0
    skipped = []
    omitted_platform_files = []
    for name, dist in selected.items():
        # The accepted interpreter may select some wheels from its user site.
        # Copy each explicitly locked distribution into the bundle; never depend
        # on that source site still existing on the target machine.
        site_source = Path(dist.locate_file('')).resolve()
        package_count = 0
        if dist.files is None:
            raise RuntimeError(f'{name} has no installed file record; install a wheel before bundling.')
        for relative_path in dist.files:
            source = Path(dist.locate_file(relative_path)).resolve()
            # Wheel console scripts are not used by this embedded backend.
            if not source.is_relative_to(site_source):
                skipped.append(str(relative_path))
                continue
            relative_path = source.relative_to(site_source)
            if name == 'setuptools' and relative_path.name in {'cli-arm64.exe', 'gui-arm64.exe'}:
                omitted_platform_files.append(f'{name}/{relative_path.as_posix()}')
                continue
            if '__pycache__' in relative_path.parts or source.suffix in {'.pyc', '.pyo'}:
                continue
            target = site_target / relative_path
            target.parent.mkdir(parents=True, exist_ok=True)
            if target.exists() and hash_file(target) != hash_file(source):
                raise RuntimeError(f'Distributions contain conflicting files: {relative_path}')
            shutil.copy2(source, target)
            count += 1
            package_count += 1
        if not package_count:
            raise RuntimeError(f'{name} has no distributable files below {site_source}')
        print(f'Bundled {name}=={dist.version}', flush=True)
    # _pth fixes the search roots; the launcher also uses -I to disable the user
    # site. The backend entry also applies to multiprocessing spawn workers.
    (runtime / 'python312._pth').write_text('.\nLib\nDLLs\nLib/site-packages\n../backend\nimport site\n', encoding='utf-8')
    backend = staging / 'backend'
    backend.mkdir()
    for name in SOURCE_DIRS:
        shutil.copytree(ROOT / name, backend / name, ignore=ignore_generated)
    (backend / 'desktop').mkdir()
    shutil.copy2(ROOT / 'desktop/backend_bootstrap.py', backend / 'desktop/backend_bootstrap.py')
    shutil.copy2(ROOT / 'run_backend.py', backend / 'run_backend.py')
    assets = Path('frontend_pyside/features/teaching_v2/assets')
    shutil.copytree(ROOT / assets, backend / assets, ignore=ignore_generated)
    dll = backend / 'native/build/optical_native.dll'
    dll.parent.mkdir(parents=True)
    shutil.copy2(ROOT / 'native/build/optical_native.dll', dll)
    shutil.copy2(ROOT / 'native/README.md', backend / 'native/README.md')
    shutil.copy2(ROOT / 'native/optical_native_core.cpp', backend / 'native/optical_native_core.cpp')
    inventory = []
    for path in sorted(staging.rglob('*')):
        if path.is_file():
            inventory.append({'path': path.relative_to(staging).as_posix(), 'bytes': path.stat().st_size,
                              'sha256': hash_file(path)})
    manifest = {'schema_version': 1, 'python_version': sys.version.split()[0], 'architecture': 'x64',
                'vc_runtime': {'version_directory': crt.parents[1].name, 'dlls': sorted(path.name for path in crt.glob('*.dll'))},
                'packages': {name: dist.version for name, dist in selected.items()},
                'native_dll_sha256': hash_file(dll), 'installed_package_files': count,
                'omitted_console_scripts': skipped, 'total_bytes': sum(row['bytes'] for row in inventory),
                'omitted_platform_files': omitted_platform_files,
                'files': inventory}
    (staging / 'resources-manifest.json').write_text(json.dumps(manifest, indent=2), encoding='utf-8')
    # Only replace our recognized generated directory, after the new bundle is complete.
    if output.exists():
        backup = inside_build(BUILD / ('desktop-resources-previous-' + staging.name.rsplit('-', 1)[-1]))
        output.rename(backup)
        try:
            staging.rename(output)
        except BaseException:
            backup.rename(output)
            raise
        shutil.rmtree(inside_build(backup))
    else:
        staging.rename(output)
    print(json.dumps({'output': str(output), 'packages': len(selected), 'files': len(inventory),
                      'bytes': manifest['total_bytes'], 'native_dll_sha256': manifest['native_dll_sha256']}), flush=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--capture-lock', action='store_true', help='Capture installed versions without staging.')
    args = parser.parse_args()
    selected = dependencies()
    versions = {name: dist.version for name, dist in selected.items()}
    if args.capture_lock:
        LOCK.write_text('# Windows x64 desktop runtime; captured from the accepted calculation environment.\n'
                        '# CPython 3.12; PySide is kept in the original checkout, not in the headless bundle.\n'
                        + ''.join(f'{name}=={version}\n' for name, version in versions.items()), encoding='utf-8')
        print(str(LOCK))
        return
    locked = dict(line.split('==', 1) for line in LOCK.read_text(encoding='utf-8').splitlines() if line and not line.startswith('#'))
    if versions != locked:
        raise RuntimeError('The installed dependency closure differs from desktop-runtime.lock.txt. '
                           'Use the locked environment, or explicitly review and recapture the lock.')
    stage(selected)


if __name__ == '__main__':
    main()
