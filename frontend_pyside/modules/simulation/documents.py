"""仿真文档组件的兼容导出层。

新代码应从 ``lens_data``、``settings`` 或 ``results`` 直接导入具体组件。
本文件保留历史聚合导入路径，保证工作台和已有集成代码不需要同时改动。
"""

# 这些导入只是重新导出，不在本模块复制实现，避免出现两份状态不同的文档类。
from .lens_data import EmptyDocument, LensDataDocument, ObjectSchematicView, SchematicDocument
from .results import ResultDocument
from .settings import CombinedSettingsDialog, EngineeringDialog, SettingsDocument

__all__ = [
    "CombinedSettingsDialog",
    "EmptyDocument",
    "EngineeringDialog",
    "LensDataDocument",
    "ObjectSchematicView",
    "ResultDocument",
    "SchematicDocument",
    "SettingsDocument",
]
