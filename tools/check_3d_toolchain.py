from __future__ import annotations
import json, shutil

TOOLS = {
    'blender': shutil.which('blender'),
    'balsam': shutil.which('balsam'),
    'gltf_validator': shutil.which('gltf_validator') or shutil.which('gltf-validator'),
}
try:
    import trimesh
    trimesh_version = getattr(trimesh, '__version__', 'unknown')
except Exception:
    trimesh_version = None
print(json.dumps({'tools': TOOLS, 'trimesh': trimesh_version}, ensure_ascii=False, indent=2))
