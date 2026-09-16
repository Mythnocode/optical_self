"""仿真“光路图”二级页面。

页面本身复用 :class:`ResultDocument` 的结果展示、指标刷新和导出能力，
这里只声明菜单元数据并固定结果类型为 ``ray_layout``。
"""

from frontend_pyside.modules.page_spec import PageSpec

from .results import ResultDocument


# ``PageSpec`` 负责描述菜单键、内部结果类型和用户可见标题。
PAGE = PageSpec(
    "simulation", "layout", "ray_layout",
    "光路图", "光线传播和聚焦；3D 从页内打开",
    "光路图", "光线传播和聚焦",
)


class LayoutTab(ResultDocument):
    """显示正式计算产生的二维光路结果。"""

    def __init__(self, context, parent=None) -> None:
        """以 ``ray_layout`` 结果类型初始化统一结果文档。"""
        # 结果文档根据 kind 选择指标、绘图数据和相关视图。
        super().__init__(context, "ray_layout", parent)


__all__ = ["LayoutTab", "PAGE"]
