"""仿真一级入口的二级页面注册表。

``PAGES`` 是仿真页面的唯一菜单顺序来源。新增、删除或调整仿真二级功能
时，应优先修改这里以及对应的页面模块，而不是修改应用壳层的路由代码。
"""

from .fiber_coupling import PAGE as FIBER_COUPLING_PAGE
from .image_quality import PAGE as IMAGE_QUALITY_PAGE
from .layout import PAGE as LAYOUT_PAGE
from .lens_data import PAGE as LENS_DATA_PAGE
from .materials import PAGE as MATERIALS_PAGE
from .wave_diffraction import PAGE as WAVE_DIFFRACTION_PAGE


# 页面顺序同时决定仿真二级功能栏的显示顺序。
PAGES = (
    LENS_DATA_PAGE,
    #MATERIALS_PAGE,
    LAYOUT_PAGE,
    IMAGE_QUALITY_PAGE,
    FIBER_COUPLING_PAGE,
    WAVE_DIFFRACTION_PAGE,
)

__all__ = ["PAGES"]
