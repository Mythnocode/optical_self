
"""光学场景构建结果缓存。

缓存静态几何和可复用场景状态，减少 3D 画布在切换结果或调整视角时重复生成
几何对象的开销；它不缓存最终图片。
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
from hashlib import sha1
import json
from typing import Any


def _digest(value: Any) -> str:
    try:
        payload = json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)
    except TypeError:
        payload = repr(value)
    return sha1(payload.encode("utf-8", errors="replace")).hexdigest()


def _dynamic_digest(value: dict) -> str:

    render_key = str(value.get("render_key", "") or "")
    if render_key:
        return f"render:{render_key}"
    return _digest(value)


@dataclass(slots=True)
class SceneLayerCache:
    static_signature: str = ""
    semistatic_signature: str = ""
    dynamic_signature: str = ""
    static_data: dict = field(default_factory=dict)
    semistatic_data: dict = field(default_factory=dict)
    dynamic_data: dict = field(default_factory=dict)

    def update(self, scene: dict) -> set[str]:
        static_data, semistatic_data, dynamic_data = split_scene_layers(scene)
        signatures = (
            _digest(static_data),
            _digest(semistatic_data),
            _dynamic_digest(dynamic_data),
        )
        changed: set[str] = set()
        if signatures[0] != self.static_signature:
            changed.add("static")
            self.static_signature = signatures[0]
            self.static_data = deepcopy(static_data)
        if signatures[1] != self.semistatic_signature:
            changed.add("semistatic")
            self.semistatic_signature = signatures[1]
            self.semistatic_data = deepcopy(semistatic_data)
        if signatures[2] != self.dynamic_signature:
            changed.add("dynamic")
            self.dynamic_signature = signatures[2]
            
            
            self.dynamic_data = dict(dynamic_data)
        return changed

    def snapshot(self) -> dict:
        value: dict = {}
        for layer_index, layer in enumerate((self.static_data, self.semistatic_data, self.dynamic_data)):
            dynamic = layer_index == 2
            for key, item in layer.items():
                copied = item if dynamic else deepcopy(item)
                if key == "objects":
                    value.setdefault("objects", []).extend(list(copied or []))
                elif key == "labels":
                    value.setdefault("labels", []).extend(list(copied or []))
                else:
                    value[key] = copied
        return value

    def clear(self) -> None:
        self.static_signature = ""
        self.semistatic_signature = ""
        self.dynamic_signature = ""
        self.static_data.clear()
        self.semistatic_data.clear()
        self.dynamic_data.clear()


def split_scene_layers(scene: dict) -> tuple[dict, dict, dict]:
    scene = dict(scene or {})
    objects = [dict(item) for item in scene.get("objects", []) if isinstance(item, dict)]
    static_objects = [
        item for item in objects if str(item.get("kind", "")) in {"detector", "image"}
    ]
    semistatic_objects = [
        item for item in objects if str(item.get("kind", "")) in {"aperture", "fiber"}
    ]
    other_objects = [
        item
        for item in objects
        if str(item.get("kind", "")) not in {"detector", "image", "aperture", "fiber"}
    ]

    surfaces = [dict(item) for item in scene.get("surfaces", []) if isinstance(item, dict)]
    
    
    geometry_surfaces = []
    selected_surface = scene.get("selected_surface")
    for item in surfaces:
        if bool(item.get("selected", False)) and not isinstance(selected_surface, dict):
            selected_surface = dict(item)
        geometry = dict(item)
        geometry.pop("selected", None)
        geometry_surfaces.append(geometry)

    static_data = {
        key: scene.get(key)
        for key in (
            "kind",
            "lens_groups",
            "axis_limits",
            "display_transform",
            "scale_label",
            "scale_mode",
            "optical_axis",
            "lens_groups",
            "show_section_plane",
        )
        if key in scene
    }
    static_data["surfaces"] = geometry_surfaces
    static_data["objects"] = static_objects

    semistatic_data = {
        "objects": semistatic_objects,
        "labels": scene.get("labels", []),
        "selected_surface_id": scene.get("selected_surface_id", ""),
        "selected_surface_index": scene.get("selected_surface_index"),
        "selected_surface": selected_surface,
        "section_plane": scene.get("section_plane", {}),
    }
    dynamic_data = {
        "objects": other_objects,
        "rays": scene.get("rays", []),
        "beam_envelope": scene.get("beam_envelope", []),
        "focus": scene.get("focus"),
        "selected_item": scene.get("selected_item", ""),
        "render_quality": scene.get("render_quality", "high"),
        "render_key": scene.get("render_key", ""),
        "source": scene.get("source", ""),
        "title": scene.get("title", ""),
        "x_label": scene.get("x_label", ""),
        "y_label": scene.get("y_label", ""),
        "z_label": scene.get("z_label", ""),
        "description": scene.get("description", ""),
    }
    return static_data, semistatic_data, dynamic_data


class DualQualitySceneCache:
    def __init__(self) -> None:
        self.preview_scene_cache = SceneLayerCache()
        self.formal_scene_cache = SceneLayerCache()

    def update(self, scene: dict, *, formal: bool = False) -> set[str]:
        cache = self.formal_scene_cache if formal else self.preview_scene_cache
        return cache.update(scene)

    def snapshot(self, *, formal: bool = False) -> dict:
        cache = self.formal_scene_cache if formal else self.preview_scene_cache
        return cache.snapshot()

    def clear(self) -> None:
        self.preview_scene_cache.clear()
        self.formal_scene_cache.clear()


__all__ = ["DualQualitySceneCache", "SceneLayerCache", "split_scene_layers"]
