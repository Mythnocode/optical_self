"""仿真一级入口的公开组件。

本包只负责把仿真页面和文档组件统一导出给工作台使用。具体的二级页面
注册在 :mod:`catalog` 中，页面实现则分别放在对应的模块里，避免所有仿真
代码重新堆回 ``workbench_shell.py``。
"""

from .documents import (
    CombinedSettingsDialog,
    EmptyDocument,
    EngineeringDialog,
    LensDataDocument,
    ResultDocument,
    SchematicDocument,
    SettingsDocument,
)
from .materials import MaterialsTab
from .fiber_coupling import FiberCouplingTab
from .image_quality import ImageQualityTab
from .layout import LayoutTab
from .wave_diffraction import WaveDiffractionTab

__all__ = [
    # 设置、占位页和结果页等公共文档组件。
    "CombinedSettingsDialog",
    "EmptyDocument",
    "EngineeringDialog",
    # 仿真的二级页面入口。
    "FiberCouplingTab",
    "LensDataDocument",
    "ImageQualityTab",
    "LayoutTab",
    "MaterialsTab",
    "ResultDocument",
    "SchematicDocument",
    "SettingsDocument",
    # 波前与衍射页面。
    "WaveDiffractionTab",
]
