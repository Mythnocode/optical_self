from __future__ import annotations

import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from frontend_pyside.features.teaching.applicability import evaluate_scene_applicability
from frontend_pyside.features.teaching.ccd_detector import parse_scan_positions_mm
from frontend_pyside.features.teaching.formal_physics import build_scene_project
from frontend_pyside.features.teaching.optical_components import DeviceFactory, TeachingOpticalSystem
from frontend_pyside.features.teaching.spatial_routing_upgrade import FlexibleSpatialExperimentModel


class TeachingOpticalSystemLoopTests(unittest.TestCase):
    def test_drag_lens_enters_optical_system_components(self) -> None:
        model = FlexibleSpatialExperimentModel()
        model.mode = "free"
        model.nodes.clear()
        model.edges.clear()
        model.add_node("laser", 100, 310, label="Laser", record=False)
        model.add_node("lens", 400, 310, label="Lens001", params={"focal_mm": 50.0}, record=False)
        system = model.sync_optical_system()
        kinds = [c.kind for c in system.components]
        labels = [c.label for c in system.components]
        self.assertIn("laser", kinds)
        self.assertIn("lens", kinds)
        self.assertTrue(any(label.startswith("Lens") or label == "Lens001" for label in labels))

    def test_device_factory_builds_typed_components(self) -> None:
        laser = DeviceFactory.create("laser", component_id="laser", label="Laser")
        lens = DeviceFactory.create("lens", component_id="lens_1", label="Lens001", params={"focal_mm": 50.0})
        ccd = DeviceFactory.create("ccd", component_id="ccd", label="CCD")
        system = TeachingOpticalSystem(components=[laser, lens, ccd])
        self.assertEqual([c.kind for c in system.components], ["laser", "lens", "ccd"])
        self.assertEqual(system.components[1].params.get("focal_mm"), 50.0)

    def test_minimal_laser_lens_ccd_scene_trace(self) -> None:
        from frontend_pyside.features.teaching.scene_bridge import experiment_model_to_physical_scene
        from teaching_runtime.physical_scene import TeachingOpticalEngineBridge

        model = FlexibleSpatialExperimentModel()
        model.load_layout_preset("minimal_laser_lens_ccd")
        report = evaluate_scene_applicability(model)
        self.assertTrue(report.allowed, msg="; ".join(report.errors))
        scene = experiment_model_to_physical_scene(model, generation=1, trace_quality="live")
        traced = TeachingOpticalEngineBridge().trace(scene)
        self.assertTrue(traced.success, msg=str(traced.errors))
        self.assertGreaterEqual(len(traced.paths), 3)
        # Off-axis sample should change height through the lens train.
        bent = False
        for path in traced.paths:
            if len(path.points) < 3:
                continue
            h0 = path.points[0].height_mm
            h1 = path.points[-1].height_mm
            if abs(h0 - 82.0) > 0.05 or abs(h1 - h0) > 0.05:
                bent = True
                break
        self.assertTrue(bent or any(p.termination_reason == "terminal_hit" for p in traced.paths))

    def test_four_lens_json_loads_optical_system(self) -> None:
        model = FlexibleSpatialExperimentModel()
        model.load_four_lens_json()
        system = model.sync_optical_system()
        kinds = [c.kind for c in system.components]
        self.assertEqual(kinds.count("lens"), 4)
        self.assertIn("laser", kinds)
        self.assertIn("ccd", kinds)
        report = evaluate_scene_applicability(model)
        self.assertTrue(report.allowed, msg="; ".join(report.errors))
        compiled = build_scene_project(model)
        self.assertIsNotNone(compiled)
        project, _image = compiled
        self.assertEqual(len(project.surfaces), 8)

    def test_scan_positions_default(self) -> None:
        self.assertEqual(
            parse_scan_positions_mm("10,15,17.5,27.5,37.5"),
            (10.0, 15.0, 17.5, 27.5, 37.5),
        )


if __name__ == "__main__":
    unittest.main()
