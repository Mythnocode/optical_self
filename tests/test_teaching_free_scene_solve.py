from __future__ import annotations

import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from frontend_pyside.features.teaching.applicability import evaluate_scene_applicability
from frontend_pyside.features.teaching.scene_bridge import experiment_model_to_physical_scene
from frontend_pyside.features.teaching.spatial_routing_upgrade import FlexibleSpatialExperimentModel
from teaching_runtime.physical_scene import TeachingOpticalEngineBridge


class FreeSceneSolveTests(unittest.TestCase):
    def test_ccd_before_lens_terminates(self) -> None:
        model = FlexibleSpatialExperimentModel()
        model.mode = "free"
        model.nodes.clear()
        model.edges.clear()
        model.add_node("laser", 100, 310, label="Laser", record=False)
        model.add_node("ccd", 300, 310, label="CCD", record=False)
        model.add_node("lens", 600, 310, label="Lens", params={"focal_mm": 50.0}, record=False)
        report = evaluate_scene_applicability(model)
        # Free placement must not hard-block when CCD is before the lens.
        self.assertTrue(report.allowed)
        scene = experiment_model_to_physical_scene(model, generation=1, trace_quality="live")
        traced = TeachingOpticalEngineBridge().trace(scene)
        self.assertTrue(traced.success, msg=str(traced.errors))
        self.assertGreater(len(traced.paths), 0)
        self.assertTrue(all(p.termination_reason == "terminal_hit" for p in traced.paths))
        self.assertTrue(all(
            p.points and str(p.points[-1].node_id or "").startswith("ccd")
            for p in traced.paths
        ))

    def test_laser_lens_ccd_hits_detector(self) -> None:
        model = FlexibleSpatialExperimentModel()
        model.load_layout_preset("minimal_laser_lens_ccd")
        scene = experiment_model_to_physical_scene(model, generation=1, trace_quality="live")
        traced = TeachingOpticalEngineBridge().trace(scene)
        self.assertTrue(traced.success, msg=str(traced.errors))
        self.assertGreater(len(traced.paths), 0)
        hits = [p.points[-1].node_id for p in traced.paths if p.points]
        self.assertTrue(any(h in {"ccd", "imaging_camera"} or (h and "ccd" in h.lower()) for h in hits) or all(
            p.termination_reason == "terminal_hit" for p in traced.paths
        ))


if __name__ == "__main__":
    unittest.main()
