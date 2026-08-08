# 顺序追迹公共入口。
from optical_core.physics.geometric.solvers.scalar_raytrace import trace_single_ray
from optical_core.physics.geometric.solvers.batch_raytrace import trace_ray_batch

__all__ = ["trace_single_ray", "trace_ray_batch"]
