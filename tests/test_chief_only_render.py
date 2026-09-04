from __future__ import annotations

import os
import unittest
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from frontend_pyside.features.teaching.spatial_routing_upgrade import (
    BeamSegmentInfo,
    FlexibleSpatialGraphicsView,
)
from frontend_pyside.features.teaching.unified_workbench import TeachingSceneSnapshot, WorkbenchMetrics


def _segment(edge_id: str, chief: bool) -> BeamSegmentInfo:
    return BeamSegmentInfo(
        edge_id=edge_id, source_id="a", target_id="b", angle_deg=0.0,
        start_x=100.0, start_y=100.0, start_z_mm=80.0,
        end_x=300.0, end_y=100.0, end_z_mm=80.0,
        is_chief_ray=chief,
    )


def _node(node_id: str):
    return SimpleNamespace(id=node_id, kind="lens", label=node_id, x=100.0, y=100.0,
                           rotation_deg=0.0, params={"z_mm": 82.0, "enabled": True})


class _Model:
    def __init__(self, segments, *, formal_rays=()) -> None:
        self.nodes = {"a": _node("a"), "b": _node("b")}
        self.edges = {"chief": object()}
        self.selected_node_id = None
        self.selected_edge_id = None
        self.mode = "free"
        self._segments = segments
        self._formal_rays = formal_rays

    def beam_segments(self):
        return tuple(self._segments)

    def scene_snapshot(self):
        metrics = WorkbenchMetrics(
            connected=True, path_node_ids=(), reached_node_ids=set(), lens_count=0,
            predicted_waist_um=0.0, target_waist_um=2.8, system_efficiency=0.0,
            receiver_efficiency=0.0, total_efficiency=0.0, output_power_mw=0.0,
            feasible=False, dominant_issue="", explanation="", latest_cause="",
        )
        return TeachingSceneSnapshot(
            1,
            metrics,
            {},
            {},
            formal_rays_mm=self._formal_rays,
            physics_source="正式光学引擎 · raytrace" if self._formal_rays else "等待正式计算",
            physics_status="verified" if self._formal_rays else "pending",
        )


class ChiefOnlyRenderTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def _make_view(self, chief_only: bool) -> FlexibleSpatialGraphicsView:
        view = FlexibleSpatialGraphicsView()
        view._render_chief_only = chief_only
        view.resize(900, 600)
        return view

    def test_topology_segments_never_render_as_physical_light(self) -> None:
        model = _Model([_segment("chief", True), _segment("sample1", False), _segment("sample2", False)])
        view = self._make_view(chief_only=False)
        view.set_model(model, preserve_view=False)
        self.assertEqual(view._formal_ray_items, [])
        self.assertEqual(view._edge_items, {})
        view.deleteLater()

    def test_formal_solver_paths_are_the_only_rendered_rays(self) -> None:
        segments = [
            _segment("chief", True),
            BeamSegmentInfo(
                edge_id="sample1", source_id="a", target_id="b", angle_deg=0.0,
                start_x=100.0, start_y=100.0, start_z_mm=80.0,
                end_x=300.0, end_y=100.0, end_z_mm=80.0,
                power_fraction=0.8, is_chief_ray=False,
            ),
            BeamSegmentInfo(
                edge_id="sample2", source_id="a", target_id="b", angle_deg=0.0,
                start_x=100.0, start_y=100.0, start_z_mm=80.0,
                end_x=300.0, end_y=100.0, end_z_mm=80.0,
                power_fraction=0.05, is_chief_ray=False,
            ),
        ]
        formal_rays = (
            ((0.0, 0.0, 0.0), (0.0, 0.0, 10.0)),
            ((0.0, 0.5, 0.0), (0.0, 0.2, 10.0)),
            ((0.0, -0.5, 0.0), (0.0, -0.2, 10.0)),
        )
        model = _Model(segments, formal_rays=formal_rays)
        view = self._make_view(chief_only=True)
        view.set_model(model, preserve_view=False)
        # Each real formal path has a glow and a foreground item.  The legacy
        # chief/sample topology segments are intentionally ignored.
        self.assertEqual(len(view._formal_ray_items), 2 * len(formal_rays))
        self.assertEqual(view._edge_items, {})
        view.deleteLater()


if __name__ == "__main__":
    unittest.main()
