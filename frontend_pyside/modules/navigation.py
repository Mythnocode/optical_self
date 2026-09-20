"""Navigation registry assembled from each primary entry's page modules."""

from __future__ import annotations

from frontend_pyside.modules.explainability.catalog import PAGES as EXPLAINABILITY_PAGES
from frontend_pyside.modules.home.catalog import SECONDARY_ITEMS as HOME_SECONDARY_ITEMS
from frontend_pyside.modules.model.catalog import PAGES as MODEL_PAGES
from frontend_pyside.modules.optimization.catalog import PAGES as OPTIMIZATION_PAGES
from frontend_pyside.modules.simulation.catalog import PAGES as SIMULATION_PAGES
from frontend_pyside.modules.teaching.catalog import SECONDARY_ITEMS as TEACHING_SECONDARY_ITEMS
from frontend_pyside.modules.page_spec import PageSpec


PRIMARY_MODULES: tuple[tuple[str, str], ...] = (
    ("home", "首页"),
    ("teaching", "教学"),
    ("simulation", "仿真"),
    ("model", "模型"),
    ("optimization", "优化"),
    ("explainability", "解释"),
)

_ENTRY_PAGES: dict[str, tuple[PageSpec, ...]] = {
    "simulation": SIMULATION_PAGES,
    "model": MODEL_PAGES,
    "optimization": OPTIMIZATION_PAGES,
    "explainability": EXPLAINABILITY_PAGES,
}

SECONDARY_ITEMS: dict[str, tuple[tuple[str, str, str], ...]] = {
    "home": HOME_SECONDARY_ITEMS,
    "teaching": TEACHING_SECONDARY_ITEMS,
    **{
        module: tuple((page.key, page.menu_title, page.menu_hint) for page in pages)
        for module, pages in _ENTRY_PAGES.items()
    },
}

# 二级功能栏每个按钮的图标名（对应 resources/icons/<名字>.svg）。
#
# 二级栏是「上图下字」：图标画在文字上方。这里不按模块分组，直接用按钮的 key
# 查表，所以同一个功能在不同模块下复用同一条登记。
#
# 换成自己的图有两种办法：
#   1. 把 SVG 丢进 frontend_pyside/resources/icons/，名字写进这张表；
#   2. 名字保持不动，直接替换 resources/icons/<名字>.svg 的内容。
# 图标本身是单色描边，颜色由代码按选中状态重新着色（见 workbench_shell 的
# _secondary_icon），所以原图用什么颜色都无所谓，建议用纯色描边。
SECONDARY_ICONS: dict[str, str] = {
    # 仿真／模型／优化／解释：用的是专门画的 PNG（1254×1254、透明底单色线条），
    # 放在 resources/icons/ 下，文件名按模块前缀 sim_* / ml_* / opt_* / explain_*。
    # 首页和教学的二级按钮仍是内置单色 SVG（教学按需求不换图）。
    "lens_data": "sim_lens_data",
    "layout": "sim_layout",
    "image_quality": "sim_spot",
    "fiber_coupling": "sim_fiber_coupling",
    "wave_diffraction": "sim_wavefront",
    "materials": "toolbox",
    # 模型
    "dataset": "ml_dataset",
    "train_result": "ml_train_result",
    "predict_eval": "ml_predict",
    # 优化
    "scan": "opt_scan",
    "opt_vars": "opt_vars",
    "opt_result": "opt_result",
    # 解释
    "global_contrib": "explain_global",
    "param_trend": "explain_trend",
    "current_system": "explain_current",
    # 首页
    "quick_start": "play",
    "help": "help",
    # 教学
    "scheme": "overview",
    "equipment": "toolbox",
    "display": "focus",
    "analysis": "intensity",
    "calculate": "play",
    "sync_to_simulation": "next",
    "sync_from_simulation": "previous",
}

# 表里没登记的 key 用这个兜底，保证所有按钮都还是「上图下字」、高度一致。
SECONDARY_ICON_FALLBACK = "workflow"

SECONDARY_DEFAULT_KIND = {
    (module, page.key): page.kind
    for module, pages in _ENTRY_PAGES.items()
    for page in pages
}
SECONDARY_DEFAULT_KIND.update({("optimization", "opt_progress"): "opt_progress"})

KIND_TO_SECONDARY = {
    (page.module, page.kind): page.key
    for pages in _ENTRY_PAGES.values()
    for page in pages
}

KIND_TITLES = {
    (page.module, page.kind): (page.title, page.subtitle)
    for pages in _ENTRY_PAGES.values()
    for page in pages
}
KIND_TITLES.update(
    {
        ("simulation", "source_schematic"): ("光源示意", "只画光源和出射光束"),
        ("simulation", "fiber_schematic"): ("光纤示意", "只画端面、模场和偏心"),
        ("simulation", "layout_3d"): ("3D 视图", "系统三维光路；示意图不画镜头"),
        ("optimization", "opt_goal"): ("优化", "目标、工程约束和准直约束"),
        ("optimization", "opt_progress"): ("优化过程", "任务运行进度和当前最优值"),
    }
)

RESULT_DOCUMENT_KINDS = frozenset({"ray_layout", "layout_3d", "spot", "coupling", "wavefront"})
FORMAL_RESULT_VIEWS: tuple[str, ...] = ("光路", "3D光路", "点列图", "PSF", "波前", "端面匹配")


def kind_titles(module: str, kind: str) -> tuple[str, str]:
    return (
        KIND_TITLES.get((module, kind))
        or KIND_TITLES.get(("simulation", kind))
        or (kind, "")
    )


__all__ = [
    "FORMAL_RESULT_VIEWS",
    "KIND_TO_SECONDARY",
    "KIND_TITLES",
    "PRIMARY_MODULES",
    "RESULT_DOCUMENT_KINDS",
    "SECONDARY_DEFAULT_KIND",
    "SECONDARY_ICON_FALLBACK",
    "SECONDARY_ICONS",
    "SECONDARY_ITEMS",
    "kind_titles",
]
