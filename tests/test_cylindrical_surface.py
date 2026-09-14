from __future__ import annotations

import math
import unittest

import numpy as np

from optical_core.models.domain.surface import OpticalSurface
from optical_core.models.domain.system import SequentialOpticalSystem
from optical_core.models.representations.ray import Ray
from optical_core.physics.geometric.formulas.paraxial import (
    matrix_from_first_to_after_last,
)
from optical_core.physics.geometric.operators.ray_surface_intersect import (
    intersect_ray_with_surface,
)
from optical_core.physics.geometric.solvers.scalar_raytrace import trace_single_ray_detailed
from optical_core.physics.geometric.solvers.trace_options import TraceOptions


def _cylinder(axis_deg: float = 0.0) -> OpticalSurface:
    return OpticalSurface(
        index=0,
        surface_type="cylindrical",
        radius_mm=50.0,
        material_before="1.0",
        material_after="1.5",
        clear_aperture_mm=10.0,
        cylinder_axis_deg=axis_deg,
    )


def _ray(x: float, y: float) -> Ray:
    return Ray(position_mm=(x, y, -10.0), direction=(0.0, 0.0, 1.0), wavelength_nm=550.0)


class CylindricalSurfaceTests(unittest.TestCase):
    def test_sag_is_invariant_along_cylinder_axis(self) -> None:
        surface = _cylinder(axis_deg=0.0)
        hit_a = intersect_ray_with_surface(_ray(0.0, 2.0), surface, vertex_z_mm=0.0)
        hit_b = intersect_ray_with_surface(_ray(4.0, 2.0), surface, vertex_z_mm=0.0)
        hit_c = intersect_ray_with_surface(_ray(0.0, 3.0), surface, vertex_z_mm=0.0)
        self.assertTrue(hit_a.valid and hit_b.valid and hit_c.valid)
        self.assertAlmostEqual(hit_a.point_mm[2], hit_b.point_mm[2], places=11)
        self.assertGreater(abs(hit_c.point_mm[2] - hit_a.point_mm[2]), 0.04)

    def test_axis_zero_only_bends_y_meridian(self) -> None:
        system = SequentialOpticalSystem(surfaces=(_cylinder(0.0),), image_distance_mm=80.0)
        options = TraceOptions(apply_surface_physics=False)
        along_axis = trace_single_ray_detailed(system, _ray(2.0, 0.0), options)
        powered = trace_single_ray_detailed(system, _ray(0.0, 2.0), options)
        self.assertEqual(along_axis.status_code, "REACHED_IMAGE")
        self.assertEqual(powered.status_code, "REACHED_IMAGE")
        self.assertAlmostEqual(along_axis.final_ray.position_mm[0], 2.0, places=10)
        self.assertAlmostEqual(along_axis.final_ray.direction[0], 0.0, places=12)
        self.assertAlmostEqual(powered.final_ray.position_mm[0], 0.0, places=12)
        self.assertLess(abs(powered.final_ray.position_mm[1]), 2.0)
        self.assertLess(powered.final_ray.direction[1], 0.0)

    def test_ninety_degree_axis_swaps_powered_meridian(self) -> None:
        system = SequentialOpticalSystem(surfaces=(_cylinder(90.0),), image_distance_mm=80.0)
        options = TraceOptions(apply_surface_physics=False)
        powered = trace_single_ray_detailed(system, _ray(2.0, 0.0), options)
        along_axis = trace_single_ray_detailed(system, _ray(0.0, 2.0), options)
        self.assertLess(abs(powered.final_ray.position_mm[0]), 2.0)
        self.assertLess(powered.final_ray.direction[0], 0.0)
        self.assertAlmostEqual(along_axis.final_ray.position_mm[1], 2.0, places=10)
        self.assertAlmostEqual(along_axis.final_ray.direction[1], 0.0, places=12)

    def test_paraxial_x_y_matrices_have_expected_power(self) -> None:
        system = SequentialOpticalSystem(surfaces=(_cylinder(0.0),))
        matrix_x = matrix_from_first_to_after_last(system, axis="x")
        matrix_y = matrix_from_first_to_after_last(system, axis="y")
        self.assertAlmostEqual(float(matrix_x[1, 0]), 0.0, places=14)
        self.assertAlmostEqual(float(matrix_y[1, 0]), -(1.5 - 1.0) / 50.0, places=14)

    def test_oblique_axis_normal_has_cross_coupling(self) -> None:
        system = SequentialOpticalSystem(surfaces=(_cylinder(45.0),), image_distance_mm=40.0)
        traced = trace_single_ray_detailed(
            system,
            _ray(2.0, 0.0),
            TraceOptions(apply_surface_physics=False),
        )
        self.assertTrue(traced.final_ray.valid)
        self.assertGreater(abs(traced.final_ray.direction[0]), 1.0e-4)
        self.assertGreater(abs(traced.final_ray.direction[1]), 1.0e-4)
        self.assertTrue(math.isclose(abs(traced.final_ray.direction[0]), abs(traced.final_ray.direction[1]), rel_tol=2e-3))


if __name__ == "__main__":
    unittest.main()
