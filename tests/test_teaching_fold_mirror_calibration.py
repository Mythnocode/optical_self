from __future__ import annotations

import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from frontend_pyside.features.teaching.scene_bridge import experiment_model_to_physical_scene
from frontend_pyside.features.teaching.spatial_routing_upgrade import (
    FlexibleSpatialExperimentModel,
    _mount_angle_for_reflection,
)
from teaching_runtime.physical_scene import (
    TeachingOpticalEngineBridge,
    TeachingPhysicalNode,
    TeachingPhysicalScene,
)


def _bridge_trace(nodes: list[TeachingPhysicalNode]):
    scene = TeachingPhysicalScene(
        nodes=tuple(nodes),
        wavelength_nm=808.0,
        input_power_mw=1.0,
        max_system_length_mm=200.0,
        generation=1,
        trace_quality="live",
    )
    return TeachingOpticalEngineBridge().trace(scene)


class FoldMirrorCalibrationTests(unittest.TestCase):
    def test_ninety_degree_fold_hits_ccd(self) -> None:
        mount = _mount_angle_for_reflection(0.0, 90.0)
        traced = _bridge_trace([
            TeachingPhysicalNode("laser", "laser", "L", 100, 310, 82, 0),
            TeachingPhysicalNode("m1", "mirror", "M1", 500, 310, 82, mount),
            TeachingPhysicalNode("ccd", "ccd", "CCD", 500, 550, 82, -90),
        ])
        self.assertTrue(traced.success, msg=str(traced.errors))
        self.assertTrue(all(p.termination_reason == "terminal_hit" for p in traced.paths))
        self.assertTrue(all(p.points and p.points[-1].node_id == "ccd" for p in traced.paths))

    def test_fold_hits_even_if_ccd_icon_faces_wrong_way(self) -> None:
        mount = _mount_angle_for_reflection(0.0, 90.0)
        traced = _bridge_trace([
            TeachingPhysicalNode("laser", "laser", "L", 100, 310, 82, 0),
            TeachingPhysicalNode("m1", "mirror", "M1", 500, 310, 82, mount),
            # Display yaw 0 would previously leave the detector edge-on to the folded beam.
            TeachingPhysicalNode("ccd", "ccd", "CCD", 500, 550, 82, 0),
        ])
        self.assertTrue(traced.success, msg=str(traced.errors))
        self.assertTrue(all(p.termination_reason == "terminal_hit" for p in traced.paths))
        self.assertTrue(all(p.points and p.points[-1].node_id == "ccd" for p in traced.paths))

    def test_fold_with_pitch_raises_beam_onto_higher_ccd(self) -> None:
        mount = _mount_angle_for_reflection(0.0, 90.0)
        traced = _bridge_trace([
            TeachingPhysicalNode("laser", "laser", "L", 100, 310, 82, 0),
            TeachingPhysicalNode("m1", "mirror", "M1", 500, 310, 82, mount, pitch_deg=12.0),
            TeachingPhysicalNode("ccd", "ccd", "CCD", 500, 550, 95, -90),
        ])
        self.assertTrue(traced.success, msg=str(traced.errors))
        self.assertTrue(all(p.termination_reason == "terminal_hit" for p in traced.paths))

    def test_negative_ninety_fold(self) -> None:
        mount = _mount_angle_for_reflection(0.0, -90.0)
        traced = _bridge_trace([
            TeachingPhysicalNode("laser", "laser", "L", 100, 400, 82, 0),
            TeachingPhysicalNode("m1", "mirror", "M1", 500, 400, 82, mount),
            TeachingPhysicalNode("ccd", "ccd", "CCD", 500, 150, 82, 90),
        ])
        self.assertTrue(traced.success, msg=str(traced.errors))
        self.assertTrue(all(p.termination_reason == "terminal_hit" for p in traced.paths))

    def test_l_shape_and_z_shape_presets(self) -> None:
        for preset in ("l_shape", "z_shape"):
            model = FlexibleSpatialExperimentModel()
            model.load_layout_preset(preset)
            scene = experiment_model_to_physical_scene(model, generation=1, trace_quality="live")
            traced = TeachingOpticalEngineBridge().trace(scene)
            self.assertTrue(traced.success, msg=f"{preset}: {traced.errors}")
            self.assertTrue(
                any(p.termination_reason == "terminal_hit" for p in traced.paths),
                msg=f"{preset} produced no terminal hit",
            )

    def test_surface_angle_override_matches_mount_convention(self) -> None:
        # Mount 90° ⇒ surface tangent 45°. Explicit surface_angle_deg=45 must fold the same way.
        traced_mount = _bridge_trace([
            TeachingPhysicalNode("laser", "laser", "L", 100, 310, 82, 0),
            TeachingPhysicalNode("m1", "mirror", "M1", 500, 310, 82, 90),
            TeachingPhysicalNode("ccd", "ccd", "CCD", 500, 550, 82, -90),
        ])
        traced_surface = _bridge_trace([
            TeachingPhysicalNode("laser", "laser", "L", 100, 310, 82, 0),
            TeachingPhysicalNode(
                "m1", "mirror", "M1", 500, 310, 82, 0,
                params={"surface_angle_deg": 45.0},
            ),
            TeachingPhysicalNode("ccd", "ccd", "CCD", 500, 550, 82, -90),
        ])
        self.assertTrue(traced_mount.success and traced_surface.success)
        self.assertTrue(all(p.termination_reason == "terminal_hit" for p in traced_mount.paths))
        self.assertTrue(all(p.termination_reason == "terminal_hit" for p in traced_surface.paths))


if __name__ == "__main__":
    unittest.main()
