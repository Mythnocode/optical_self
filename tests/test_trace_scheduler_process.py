from __future__ import annotations

import time
import unittest


class TraceSchedulerProcessModeTests(unittest.TestCase):
    def test_process_mode_returns_latest_generation(self) -> None:
        from teaching_runtime.trace_scheduler import TeachingTraceScheduler
        from teaching_runtime.physical_scene import TeachingPhysicalNode, TeachingPhysicalScene

        def _scene(generation: int) -> TeachingPhysicalScene:
            nodes = (
                TeachingPhysicalNode("laser", "laser", "激光器", 120, 310, 82, 0.0, params={"beam_radius_mm": 0.72}),
                TeachingPhysicalNode("lens", "lens", "L1", 610, 310, 82, 0.0, params={"focal_mm": 50.0, "material": "N-BK7"}),
                TeachingPhysicalNode("fiber", "fiber", "五轴光纤架", 1120, 310, 82, 180.0),
            )
            return TeachingPhysicalScene(
                nodes=nodes, wavelength_nm=808.0, input_power_mw=100.0,
                max_system_length_mm=140.0, generation=generation, trace_quality="settled",
            )

        scheduler = TeachingTraceScheduler(process_mode=True)
        try:
            scheduler.submit(_scene(11), generation=11, quality="settled")
            result = None
            deadline = time.time() + 60
            while time.time() < deadline and result is None:
                result = scheduler.poll_latest()
                time.sleep(0.02)
            self.assertIsNotNone(result)
            self.assertEqual(result.generation, 11)
            self.assertTrue(result.success)
            self.assertGreater(len(result.paths), 0)
        finally:
            scheduler.close()


if __name__ == "__main__":
    unittest.main()
