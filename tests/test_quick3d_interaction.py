from __future__ import annotations

import os
import unittest
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from frontend_pyside.features.teaching.quick3d_bridge import TeachingQuick3DBridge


class _Model:
    def __init__(self) -> None:
        self.nodes = {
            "lens": SimpleNamespace(
                id="lens", kind="lens", label="L1", x=300.0, y=430.0,
                rotation_deg=0.0, params={"z_mm": 82.0},
            )
        }
        self.edges = {}
        self.revision = 1
        self.moves = []
        self.rotations = []

    def beam_segments(self):
        return ()

    def engine_trace_status(self):
        return {"applied_generation": 1}

    def move_node_3d(self, node_id, x, y, z_mm, *, record):
        self.moves.append((node_id, x, y, z_mm, record))
        node = self.nodes[node_id]
        node.x, node.y, node.params["z_mm"] = x, y, z_mm

    def set_orientation(self, node_id, *, yaw_deg, pitch_deg, roll_deg, record):
        self.rotations.append((node_id, yaw_deg, pitch_deg, roll_deg, record))
        node = self.nodes[node_id]
        node.rotation_deg = yaw_deg
        node.params["pitch_deg"] = pitch_deg
        node.params["roll_deg"] = roll_deg


class Quick3DBridgeInteractionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.bridge = TeachingQuick3DBridge()
        self.model = _Model()
        self.bridge._model = self.model

    def test_live_move_updates_model_without_history_record(self) -> None:
        self.bridge.move_node_3d_live("lens", 420.0, 500.0, 92.0)
        self.assertEqual(self.model.moves, [("lens", 420.0, 500.0, 92.0, False)])
        self.assertEqual(self.model.nodes["lens"].x, 420.0)

    def test_live_rotation_updates_model_without_history_record(self) -> None:
        self.bridge.set_orientation_live("lens", 25.0, 8.0, 3.0)
        self.assertEqual(self.model.rotations, [("lens", 25.0, 8.0, 3.0, False)])
        self.assertEqual(self.model.nodes["lens"].rotation_deg, 25.0)

    def test_commit_emits_a_single_change_signal(self) -> None:
        changes = []
        self.bridge.nodeChanged.connect(lambda node_id, action: changes.append((node_id, action)))
        self.bridge.commit_node_change("lens", "3D移动")
        self.assertEqual(changes, [("lens", "3D移动")])
        self.assertEqual(self.model.moves, [])
        self.assertEqual(self.model.rotations, [])


if __name__ == "__main__":
    unittest.main()
