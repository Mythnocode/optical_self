from __future__ import annotations

import math
import os
import unittest
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from optical_core.physics.geometric.formulas.surface_sag import sag_conic_asphere

from frontend_pyside.features.teaching.experiment_scene import (
    SCENE_MM_PER_PX,
    build_ray_mapping,
    formal_rays_scene_3d,
    formal_rays_world_3d,
    project_formal_rays_2d,
)
from frontend_pyside.features.teaching.formal_physics import build_scene_project
from frontend_pyside.features.teaching.unified_workbench import ExperimentNode


def _coupling_model(*, laser: bool = True) -> SimpleNamespace:
    nodes = {
        "l1": ExperimentNode(id="l1", kind="lens", label="L1", x=1040.0, y=310.0, params={"focal_mm": 50.0}),
        "l2": ExperimentNode(id="l2", kind="lens", label="L2", x=1155.0, y=310.0, params={"focal_mm": 12.0}),
        "fiber": ExperimentNode(id="fiber", kind="fiber", label="光纤", x=1370.0, y=310.0, rotation_deg=180.0, params={}),
    }
    if laser:
        nodes["laser"] = ExperimentNode(id="laser", kind="laser", label="激光器", x=80.0, y=310.0)
    return SimpleNamespace(nodes=nodes, wavelength_nm=808.0, receiver_mode_radius_um=2.8)


# A single on-axis ray sampled at the first lens (z=0), the second lens and the
# fiber — the z frame build_scene_project compiles (0.76 mm per scene pixel).
_RAYS = (((0.0, 0.0, 0.0), (0.0, 0.0, 87.4), (0.0, 0.0, 250.8)),)


class TeachingRayAlignmentTests(unittest.TestCase):
    def test_build_scene_project_compiles_lenses_and_fiber(self) -> None:
        model = _coupling_model()
        compiled = build_scene_project(model)
        self.assertIsNotNone(compiled)
        project, image_distance_mm = compiled
        self.assertEqual(len(project.surfaces), 4)
        radius = 2.0 * (1.5168 - 1.0) * 50.0
        self.assertAlmostEqual(project.surfaces[0].radius_mm, radius, places=6)
        self.assertAlmostEqual(project.surfaces[1].radius_mm, -radius, places=6)
        # L2 front sits at (1155 - 1040) * 0.76 = 87.4 mm.
        self.assertAlmostEqual(
            sum(surface.thickness_mm for surface in project.surfaces[:2]), 87.4, places=6
        )
        # Fiber sits at (1370 - 1040) * 0.76 = 250.8 mm; image plane after L2 back.
        self.assertAlmostEqual(image_distance_mm, 250.8 - 87.4 - 3.0, places=6)
        self.assertAlmostEqual(project.wavelength_nm, 808.0, places=6)

    def test_build_scene_project_requires_lens_and_fiber(self) -> None:
        no_fiber = _coupling_model()
        del no_fiber.nodes["fiber"]
        self.assertIsNone(build_scene_project(no_fiber))
        no_lens = _coupling_model()
        del no_lens.nodes["l1"]
        del no_lens.nodes["l2"]
        self.assertIsNone(build_scene_project(no_lens))
        zero_focal = _coupling_model()
        zero_focal.nodes["l1"].params["focal_mm"] = 0.0
        zero_focal.nodes["l2"].params["focal_mm"] = 0.0
        # Focal length 0 still compiles a sequential project with flat surfaces;
        # scene applicability marks invalid radii separately.  Keep this as a
        # soft compile for tooling, but radii are zero.
        compiled = build_scene_project(zero_focal)
        self.assertIsNotNone(compiled)
        self.assertEqual(compiled[0].surfaces[0].radius_mm, 0.0)

    def test_build_scene_project_rejects_folded_layout(self) -> None:
        # An L-shaped path collapses the coupling train onto one scene x; the
        # sequential engine cannot model a folded path, so no project is built.
        model = _coupling_model()
        for node in model.nodes.values():
            if node.kind in {"lens", "fiber"}:
                node.x = 570.0
        self.assertIsNone(build_scene_project(model))

    def test_ray_mapping_anchored_at_first_lens(self) -> None:
        model = _coupling_model()
        mapping = build_ray_mapping(model, _RAYS)
        self.assertIsNotNone(mapping)
        self.assertAlmostEqual(mapping.scene_x(0.0), 1040.0, places=6)
        self.assertAlmostEqual(mapping.scene_x(87.4), 1155.0, places=6)
        self.assertAlmostEqual(mapping.scene_x(250.8), 1370.0, places=6)

    def test_side_projection_lands_on_lens_and_fiber(self) -> None:
        model = _coupling_model(laser=False)
        projected = project_formal_rays_2d(model, _RAYS, plane="side", rail_y=310.0)
        self.assertEqual(len(projected), 1)
        points = projected[0]
        self.assertAlmostEqual(points[0][0], 1040.0, places=6)
        self.assertAlmostEqual(points[1][0], 1155.0, places=6)
        self.assertAlmostEqual(points[2][0], 1370.0, places=6)
        self.assertAlmostEqual(points[0][1], 310.0, places=6)

    def test_beam_extends_back_to_laser(self) -> None:
        model = _coupling_model(laser=True)
        projected = project_formal_rays_2d(model, _RAYS, plane="side", rail_y=310.0)
        points = projected[0]
        self.assertEqual(len(points), 4)
        self.assertAlmostEqual(points[0][0], 80.0, places=6)  # laser scene x
        self.assertAlmostEqual(points[1][0], 1040.0, places=6)
        self.assertAlmostEqual(points[2][0], 1155.0, places=6)
        self.assertAlmostEqual(points[3][0], 1370.0, places=6)

    def test_3d_scene_projection_lands_on_lens_and_fiber(self) -> None:
        model = _coupling_model(laser=False)
        rays = formal_rays_scene_3d(model, _RAYS)
        self.assertEqual(len(rays), 1)
        points = rays[0]
        self.assertAlmostEqual(points[0][0], 1040.0, places=6)
        self.assertAlmostEqual(points[1][0], 1155.0, places=6)
        self.assertAlmostEqual(points[2][0], 1370.0, places=6)
        # On-axis rays keep the rail depth and the 82 mm optical height.
        self.assertAlmostEqual(points[0][1], 310.0, places=6)
        self.assertAlmostEqual(points[0][2], 82.0, places=6)

    def test_3d_world_rays_aligned_to_rail_depth(self) -> None:
        model = _coupling_model(laser=False)
        rays = formal_rays_world_3d(model, _RAYS)
        self.assertEqual(len(rays), 1)
        points = rays[0]
        rail_depth = (310.0 - 450.0) * 0.62  # preset rail scene y = 310
        for point in points:
            self.assertAlmostEqual(point[2], rail_depth, places=6)
        # Endpoint world-x matches the first/last formal stations (densified
        # polylines insert free-space samples between surfaces).
        self.assertAlmostEqual(points[0][0], (1040.0 - 800.0) * 0.76, places=6)
        self.assertAlmostEqual(points[-1][0], (1370.0 - 800.0) * 0.76, places=6)
        # on-axis ray keeps the 82 mm optical height (world y = 52)
        self.assertAlmostEqual(points[0][1], 52.0, places=6)

    def test_sag_beyond_radius_returns_nan_not_crash(self) -> None:
        # A ray beyond the sphere's equator must not abort the whole trace.
        value = sag_conic_asphere(30.0, radius_mm=12.4)
        self.assertTrue(math.isnan(float(value)))
        inside = sag_conic_asphere(2.0, radius_mm=12.4)
        self.assertTrue(math.isfinite(float(inside)))

    def test_scene_mm_per_px_constant(self) -> None:
        self.assertAlmostEqual(SCENE_MM_PER_PX, 0.76, places=9)


if __name__ == "__main__":
    unittest.main()


def test_teaching_scene_solver_accepts_laser_only_train() -> None:
    from frontend_pyside.features.teaching.scene_bridge import experiment_model_to_physical_scene
    from frontend_pyside.features.teaching.spatial_routing_upgrade import FlexibleSpatialExperimentModel
    from teaching_runtime.physical_scene import TeachingOpticalEngineBridge

    model = FlexibleSpatialExperimentModel()
    model.mode = "free"
    model.nodes.clear()
    model.edges.clear()
    model.add_node("laser", 100, 310, record=False)
    model.add_node("ccd", 500, 310, record=False)
    scene = experiment_model_to_physical_scene(model, generation=1, trace_quality="live")
    traced = TeachingOpticalEngineBridge().trace(scene)
    assert traced.success
    assert len(traced.paths) > 0
    assert all(p.termination_reason == "terminal_hit" for p in traced.paths)
