"""仿真“波前与衍射”二级页面。

页面使用统一结果文档，但将结果类型设为 ``wavefront``，由结果适配器
选择波前图或点扩散函数（PSF）进行展示。
"""

from frontend_pyside.modules.page_spec import PageSpec

from .results import ResultDocument


# 页面注册信息由仿真目录汇总，不在工作台壳层重复声明。
PAGE = PageSpec(
    "simulation", "wave_diffraction", "wavefront",
    "波前与衍射", "波前图或 PSF",
    "波前与衍射", "波前图或 PSF",
)


class WaveDiffractionTab(ResultDocument):
    """显示波前 RMS、斯特列尔比以及波前/PSF 图。"""

    def __init__(self, context, parent=None) -> None:
        """以 ``wavefront`` 结果类型初始化统一结果文档。"""
        # 结果类型决定页面最终从正式结果中取哪一组绘图数据。
        super().__init__(context, "wavefront", parent)


__all__ = ["PAGE", "WaveDiffractionTab"]
