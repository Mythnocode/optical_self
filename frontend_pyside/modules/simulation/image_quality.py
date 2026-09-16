"""仿真“光斑图”二级页面。

该页面复用统一结果文档，只把结果类型设置为 ``spot``，从而显示点列图、
光斑尺寸和峰值位置等图表及指标。
"""

from frontend_pyside.modules.page_spec import PageSpec

from .results import ResultDocument


# 页面描述被仿真目录和工作台用于生成菜单及路由。
PAGE = PageSpec(
    "simulation", "image_quality", "spot",
    "光斑图", "光斑、点列和焦面尺寸",
    "光斑图", "接收面光斑、尺寸和功率",
)


class ImageQualityTab(ResultDocument):
    """显示接收面上的光斑和图像质量结果。"""

    def __init__(self, context, parent=None) -> None:
        """以 ``spot`` 结果类型初始化统一结果文档。"""
        # ``spot`` 是结果适配器识别的内部结果类型，不是菜单显示文本。
        super().__init__(context, "spot", parent)


__all__ = ["ImageQualityTab", "PAGE"]
