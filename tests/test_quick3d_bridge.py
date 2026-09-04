from __future__ import annotations

import os
import unittest
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from frontend_pyside.features.teaching.quick3d_bridge import flatten_scene


class BridgeFlattenTests(unittest.TestCase):
    def test_flattens_nodes_and_segments(self) -> None:
        node_a = SimpleNamespace(
            id="a", kind="laser", label="Laser", x=10, y=20,
            rotation_deg=5, params={"z_mm": 81, "pitch_deg": 2, "enabled": True},
        )
        node_b = SimpleNamespace(
            id="b", kind="fiber", label="Fiber", x=30, y=20,
            rotation_deg=180, params={"z_mm": 82},
        )
        segment = SimpleNamespace(
            edge_id="e1", source_id="a", target_id="b", start_x=10, start_y=20,
            start_z_mm=81, end_x=30, end_y=20, end_z_mm=82,
            power_fraction=0.7, is_chief_ray=True,
        )
        model = SimpleNamespace(
            nodes={"a": node_a, "b": node_b}, selected_node_id="b",
            edges={"e1": object()}, revision=4,
            beam_segments=lambda: (segment,),
            engine_trace_status=lambda: {"applied_generation": 9},
        )
        result = flatten_scene(model, SimpleNamespace(current_radii={"a": 3, "b": 5}))
        self.assertEqual(result["revision"], 4)
        self.assertEqual(result["generation"], 9)
        self.assertTrue(result["nodes"][1]["selected"])
        self.assertEqual(result["segments"][0]["id"], "e1")
        self.assertEqual(result["segments"][0]["power"], 0.7)

    def test_filters_non_finite_beam_coordinates(self) -> None:
        segment = SimpleNamespace(
            edge_id="bad", source_id="a", target_id="b", start_x=float("nan"),
            start_y=0, start_z_mm=0, end_x=1, end_y=1, end_z_mm=1,
            power_fraction=1, is_chief_ray=False,
        )
        model = SimpleNamespace(nodes={}, edges={}, revision=0, selected_node_id=None,
                                beam_segments=lambda: (segment,),
                                engine_trace_status=lambda: {})
        self.assertEqual(flatten_scene(model)["segments"], [])


if __name__ == "__main__":
    unittest.main()
