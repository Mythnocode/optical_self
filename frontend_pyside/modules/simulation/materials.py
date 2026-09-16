"""仿真“材料库”二级页面入口。

材料库的具体交互仍由底层仿真能力模块实现；本文件只负责把它挂载为
仿真一级入口下的一个标准 ``PageSpec`` 页面。
"""

from frontend_pyside.features.simulation.material_library import MaterialLibraryDocument
from frontend_pyside.modules.page_spec import PageSpec


# 页面元数据用于生成二级菜单、路由键和工作台标题。
PAGE = PageSpec(
    "simulation", "materials", "material_library",
    "材料库", "平台支持的材料和自定义材料",
    "材料库", "平台材料和自定义材料",
)


class MaterialsTab(MaterialLibraryDocument):
    """把材料库文档挂载到仿真“材料库”二级页面。"""


__all__ = ["MaterialsTab"]
