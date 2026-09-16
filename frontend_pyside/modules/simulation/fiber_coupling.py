"""仿真“光纤耦合”二级页面。

页面沿用统一结果文档的生命周期和导出能力，使用 ``coupling`` 结果类型
展示系统透过率、端面接收效率和总耦合效率。
"""

from frontend_pyside.modules.page_spec import PageSpec

from .results import ResultDocument


# 页面元数据与结果 kind 分离：前者面向导航，后者面向结果适配器。
PAGE = PageSpec(
    "simulation", "fiber_coupling", "coupling",
    "光纤耦合", "光纤耦合效率相关图",
    "光纤耦合", "光纤耦合效率相关图",
)


class FiberCouplingTab(ResultDocument):
    """显示正式计算得到的光纤耦合结果。"""

    def __init__(self, context, parent=None) -> None:
        """以 ``coupling`` 结果类型初始化统一结果文档。"""
        # ``ResultDocument`` 会根据该 kind 选择耦合专用指标和图表。
        super().__init__(context, "coupling", parent)


__all__ = ["FiberCouplingTab", "PAGE"]
