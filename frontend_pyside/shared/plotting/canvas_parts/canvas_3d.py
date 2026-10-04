"""3D 绘图入口和渲染器组合层。

它根据载荷选择动态场景或静态场景渲染实现，并把结果挂接到统一的
``PlotCanvas``；具体几何和 artist 细节分散在 3D 渲染模块中。
"""

from __future__ import annotations

from frontend_pyside.shared.plotting.canvas_3d_rendering import render_dynamic_scene
from frontend_pyside.shared.plotting.canvas_3d_static_parts import render_static_scene
from frontend_pyside.shared.plotting.canvas_view import fit_optical_scene_3d
from frontend_pyside.resources import theme_tokens as theme
from .data_utils import _remove_artists, _scene_static_signature

class Canvas3DMixin:
    def _optical_scene_3d(self, ax, data: dict) -> None:
        from shared_presentation.plotting.scene_drawing import draw_optical_scene_3d
        static, dynamic = draw_optical_scene_3d(ax, data)
        self._scene_static_signature = _scene_static_signature(data)
        self._static_scene_artists = static
        self._dynamic_scene_artists = dynamic

        self._interaction.update_artists(
            high_quality=[*static.high_quality, *dynamic.high_quality],
            ray_collections=dynamic.ray_collections,
            pick_artists=static.surface_pick_artists,
        )
        self._hover.update(
            pick_artists=static.surface_pick_artists,
            surfaces=list(data.get("surfaces", [])),
        )

    def _update_optical_scene_dynamic(self, data: dict) -> None:

        if self._axis is None or self._static_scene_artists is None:
            return
        old = self._dynamic_scene_artists
        reuse_collections = list(old.ray_collections) if old is not None else None
        reuse_keys = list(old.ray_group_keys) if old is not None else None
        if old is not None:
            
            
            _remove_artists([*old.high_quality, *old.persistent])
        dynamic = render_dynamic_scene(
            self._axis,
            data,
            reuse_ray_collections=reuse_collections,
            reuse_ray_group_keys=reuse_keys,
        )
        self._dynamic_scene_artists = dynamic
        self._interaction.update_artists(
            high_quality=[*self._static_scene_artists.high_quality, *dynamic.high_quality],
            ray_collections=dynamic.ray_collections,
            pick_artists=self._static_scene_artists.surface_pick_artists,
        )
