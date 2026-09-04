from __future__ import annotations

"""Stage an external 3D asset for Chen's visual-only teaching asset pipeline.

This tool does not make an asset part of the runtime automatically.  It records
provenance, hashes the source, performs a geometry sanity check with trimesh when
possible, and reports whether Blender/Balsam/glTF Validator are available for the
next normalization/build gates.
"""

import argparse
import hashlib
import json
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SUPPORTED = {'.blend', '.fbx', '.obj', '.stl', '.gltf', '.glb'}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open('rb') as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def geometry_probe(path: Path) -> dict[str, object]:
    result: dict[str, object] = {'available': False, 'errors': []}
    try:
        import trimesh
    except Exception as exc:
        result['errors'].append(f'trimesh unavailable: {exc}')
        return result
    if path.suffix.lower() == '.blend':
        result['errors'].append('BLEND geometry probe requires Blender; source is staged only')
        return result
    try:
        scene = trimesh.load(path, force='scene', process=False)
        geometries = list(scene.geometry.values())
        vertices = sum(len(mesh.vertices) for mesh in geometries if hasattr(mesh, 'vertices'))
        faces = sum(len(mesh.faces) for mesh in geometries if hasattr(mesh, 'faces'))
        bounds = scene.bounds.tolist() if scene.bounds is not None else None
        extents = scene.extents.tolist() if scene.extents is not None else None
        result.update({
            'available': True,
            'geometry_count': len(geometries),
            'vertices': int(vertices),
            'triangles': int(faces),
            'bounds_native': bounds,
            'extents_native': extents,
            'units': getattr(scene, 'units', None),
        })
    except Exception as exc:
        result['errors'].append(f'geometry load failed: {type(exc).__name__}: {exc}')
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description='Stage an external teaching 3D asset with provenance checks.')
    parser.add_argument('path', type=Path)
    parser.add_argument('--asset-id', required=True)
    parser.add_argument('--category', required=True)
    parser.add_argument('--author', required=True)
    parser.add_argument('--source-url', required=True)
    parser.add_argument('--license', required=True)
    parser.add_argument('--redistribution-allowed', action='store_true')
    parser.add_argument('--modification-allowed', action='store_true')
    parser.add_argument('--size-mm', nargs=3, type=float, metavar=('X', 'Y', 'Z'), required=True)
    parser.add_argument('--optical-origin-mm', nargs=3, type=float, default=(0.0, 0.0, 0.0))
    parser.add_argument('--optical-axis', nargs=3, type=float, default=(1.0, 0.0, 0.0))
    parser.add_argument('--mount-origin-mm', nargs=3, type=float, default=(0.0, 0.0, 0.0))
    parser.add_argument('--copy-source', action='store_true')
    args = parser.parse_args()

    path = args.path.resolve()
    errors: list[str] = []
    if not path.is_file():
        errors.append('source file does not exist')
    if path.suffix.lower() not in SUPPORTED:
        errors.append(f'unsupported extension: {path.suffix}')
    if not args.redistribution_allowed:
        errors.append('redistribution permission was not confirmed')
    if not args.modification_allowed:
        errors.append('modification permission was not confirmed')
    if any(value <= 0 for value in args.size_mm):
        errors.append('all physical size dimensions must be > 0')
    if args.license.strip().lower() in {'unknown', 'none', ''}:
        errors.append('license is unknown')

    geometry = geometry_probe(path) if path.is_file() else {'available': False, 'errors': []}
    digest = sha256(path) if path.is_file() else ''
    toolchain = {
        'blender': shutil.which('blender'),
        'balsam': shutil.which('balsam'),
        'gltf_validator': shutil.which('gltf_validator') or shutil.which('gltf-validator'),
    }
    manifest = {
        'schema_version': 1,
        'asset_id': args.asset_id,
        'category': args.category,
        'status': 'REJECTED' if errors else 'STAGED',
        'source': {
            'filename': path.name,
            'author': args.author,
            'source_url': args.source_url,
            'download_or_ingest_date': datetime.now(timezone.utc).isoformat(),
            'sha256': digest,
            'license': args.license,
            'redistribution_allowed': bool(args.redistribution_allowed),
            'modification_allowed': bool(args.modification_allowed),
        },
        'physical': {'unit': 'mm', 'size_mm': list(args.size_mm)},
        'anchors': {
            'optical_origin_mm': list(args.optical_origin_mm),
            'optical_axis': list(args.optical_axis),
            'mount_origin_mm': list(args.mount_origin_mm),
        },
        'geometry_probe': geometry,
        'toolchain': toolchain,
        'gate_errors': errors,
        'next_gate': 'Normalize to GLB, validate, build Qt asset, then run visual/performance regression.',
        'physics_role': 'visual_only',
    }

    manifest_dir = ROOT / 'assets_3d/manifests'
    report_dir = ROOT / 'assets_3d/reports'
    manifest_dir.mkdir(parents=True, exist_ok=True)
    report_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = manifest_dir / f'{args.asset_id}.json'
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding='utf-8')

    if args.copy_source and not errors:
        source_dir = ROOT / 'assets_3d/source' / args.asset_id
        source_dir.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, source_dir / path.name)

    print(json.dumps(manifest, ensure_ascii=False, indent=2))
    print('manifest:', manifest_path)
    return 1 if errors else 0


if __name__ == '__main__':
    raise SystemExit(main())
