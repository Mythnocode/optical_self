"""光学核心统一异常。"""

class OpticalCoreError(Exception):
    """光学仿真内核异常基类。"""

class OpticalComputationError(OpticalCoreError):
    """光学计算失败。"""
