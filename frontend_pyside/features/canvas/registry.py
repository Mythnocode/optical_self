"""节点注册表：ShellAction → NodeSpec（node_kind 分流左右栏 + 依赖规则）。

画布中心化：所有功能都落为原生画布节点，不再弹独立窗口——
- source 类（镜头组、计算设置）→ 左栏，依赖图根（无 ×，不可删除）；
- view 类（光路/PSF/相位/模场/MTF/点列…）→ 右栏，绑定 1 个 source；
- tool 类（参数研究/容差/优化）→ 右栏任务节点：可编辑参数 + ✓确认 + ×关闭；
- summary 类（项目/模型/数据/任务摘要）→ 纯自绘关键状态，禁止嵌入完整页面。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from frontend_pyside.app.shell_catalog import CATEGORY_BY_KEY, CATEGORIES, ShellAction


@dataclass(frozen=True, slots=True)
class NodeSpec:
    key: str
    title: str
    icon_name: str
    group: str  # 所属分类 key（system/analysis/research/surrogate/experiment/teaching）
    node_kind: str  # source / view / tool / summary
    payload: dict[str, Any] = field(default_factory=dict)
    analyses: frozenset[str] = frozenset()  # view 节点声明的分析种类（脏传播用）
    hint: str = ""
    default_w: float = 230.0
    default_h: float = 170.0
    singleton: bool = True  # 同类节点画布上只保留一个（镜头组/结果目录等）
    factory_path: str = ""  # 保留快照兼容字段；生产节点必须为空


# ---- 画布原生节点 spec --------------------------------------------------------

# key → (node_kind, analyses, 单例, 默认尺寸)
_CANVAS_SPECS: dict[str, dict[str, Any]] = {
    # 数据源（左栏）；compute_settings 是系统域配置 → 左栏
    "lens_editor": {"node_kind": "source", "analyses": set(), "singleton": True, "default": (720, 380)},
    "compute_settings": {"node_kind": "tool", "singleton": True, "default": (360, 230), "side": "left"},
    # 分析视图（右栏）；analyses = 脏传播过滤标签（invalidation_map 匹配键）
    "system_view": {"node_kind": "view", "analyses": {"raytrace"}, "default": (230, 170)},
    "propagation": {"node_kind": "view", "analyses": {"raytrace", "beam_propagation"}, "default": (230, 170)},
    "focal": {"node_kind": "view", "analyses": {"psf"}, "default": (230, 170)},
    "field": {"node_kind": "view", "analyses": {"psf"}, "default": (230, 170)},
    "mtf": {"node_kind": "view", "analyses": {"mtf"}, "default": (230, 170)},
    "wave": {"node_kind": "view", "analyses": {"spot"}, "default": (230, 170)},
    "intensity": {"node_kind": "view", "analyses": {"coupling"}, "default": (230, 170)},
    "mode": {"node_kind": "view", "analyses": {"coupling"}, "default": (230, 170)},
    "all_results": {"node_kind": "view", "analyses": {"catalogue"}, "singleton": True, "default": (420, 320)},
    # 工具任务：配置通过节点左侧齿轮的分类参数胶囊完成
    "scan": {"node_kind": "tool", "singleton": True, "analyses": {"raytrace", "coupling", "psf"}, "default": (400, 430)},
    "tolerance": {"node_kind": "tool", "singleton": True, "analyses": {"raytrace", "coupling", "psf"}, "default": (400, 430)},
    "optimize": {"node_kind": "tool", "singleton": True, "analyses": {"raytrace", "coupling", "psf"}, "default": (400, 430)},
    # 代理模型：以轻量配置节点呈现
    "random_forest": {"node_kind": "tool", "singleton": False, "default": (330, 190)},
    "xgboost_physics_residual": {"node_kind": "tool", "singleton": False, "default": (350, 205)},
    "bilstm_structure_sequence": {"node_kind": "tool", "singleton": False, "default": (350, 220)},
    # 数据集既是结果索引，也是模型训练的正式数据源；必须是原生节点，
    # 不能继续把旧版数据页面塞进中心画布。
    "data": {"node_kind": "data", "singleton": True, "default": (420, 260), "side": "right"},
}

# 原先嵌入完整页面的入口全部改为原生节点。无 factory 字段是硬约束。
_NATIVE_SUMMARY_SPECS: dict[str, dict[str, Any]] = {
    "overview": {"node_kind": "summary", "side": "left", "size": (380, 250)},
    "system": {"node_kind": "summary", "side": "left", "size": (400, 240)},
    "model_build": {"node_kind": "summary", "side": "right", "size": (380, 220)},
    "forward": {"node_kind": "summary", "side": "right", "size": (400, 250)},
    "forward_result": {"node_kind": "summary", "side": "right", "size": (440, 320), "singleton": False},
    "model_explain": {"node_kind": "summary", "side": "right", "size": (420, 280)},
    "model_manage": {"node_kind": "summary", "side": "right", "size": (400, 240)},
    "tasks": {"node_kind": "summary", "side": "right", "size": (400, 240)},
    # 两类逆向设计接入真实 optimization task 管线，不使用摘要占位。
    "physical_inverse": {"node_kind": "tool", "side": "right", "size": (420, 430), "analyses": {"raytrace", "coupling", "psf"}},
    "ml_inverse": {"node_kind": "tool", "side": "right", "size": (440, 450), "analyses": {"raytrace", "coupling", "psf"}},
}

_SPECIAL_SPECS: dict[str, dict[str, Any]] = {}

# 画布分析图 key → 图表种类（chart_view 渲染分派）
CHART_KIND_BY_KEY = {
    "system_view": "layout",
    "propagation": "propagation",
    "focal": "psf",
    "field": "phase",
    "mtf": "mtf",
    "wave": "spot",
    "intensity": "intensity",
    "mode": "mode",
    "all_results": "catalogue",
}

# 画布直接落节点的 key 集合（全部 ShellAction 均已节点化）
CANVAS_NODE_KEYS = frozenset(_CANVAS_SPECS) | frozenset(_NATIVE_SUMMARY_SPECS) | frozenset(_SPECIAL_SPECS)


def _spec_from_action(action: ShellAction, group: str) -> NodeSpec:
    extra = _CANVAS_SPECS.get(action.key) or _NATIVE_SUMMARY_SPECS.get(action.key) or _SPECIAL_SPECS.get(action.key, {})
    kind = str(extra.get("node_kind", "tool"))
    default = extra.get("default") or extra.get("size") or (230.0, 170.0)
    payload = dict(action.payload or {})
    payload.update(dict(extra.get("payload") or {}))
    if action.target:
        payload.setdefault("target", action.target)
    return NodeSpec(
        key=action.key,
        title=action.title,
        icon_name=action.icon_name,
        group=group,
        node_kind=kind,
        payload=payload,
        analyses=frozenset(extra.get("analyses", set())),
        hint=action.hint,
        default_w=float(default[0]),
        default_h=float(default[1]),
        singleton=bool(extra.get("singleton", True)),
        factory_path="",
    )


# 画布补充的 MTF / 光强节点（CATEGORIES 无对应 ShellAction）
_NODE_SPECS: dict[str, NodeSpec] = {}
for category in CATEGORIES:
    for _group_title, actions in category.groups:
        for action in actions:
            _NODE_SPECS[action.key] = _spec_from_action(action, category.key)
_NODE_SPECS["mtf"] = _spec_from_action(
    ShellAction("mtf", "MTF 曲线", "chart", "simulation", "simulation.view", {"view": "MTF"}, hint="子午 / 弧矢切向 MTF"),
    "analysis",
)
_NODE_SPECS["intensity"] = _spec_from_action(
    ShellAction("intensity", "光强分布", "intensity", "simulation", "simulation.view", {"view": "光强"}, hint="焦面光强分布"),
    "analysis",
)
# 正向预测完成后由壳层自动生成，不出现在功能栏。
_NODE_SPECS["forward_result"] = NodeSpec(
    key="forward_result",
    title="预测结果",
    icon_name="chart",
    group="machine_learning",
    node_kind="summary",
    default_w=440.0,
    default_h=320.0,
    singleton=False,
    hint="当前透镜参数与正式基线、残差的对照",
)

# 左右栏分流：source / 教学摘要 → 左；view/tool / 任务摘要 → 右
LEFT_RAIL_KINDS = ("source",)
_LEFT_NATIVE_KEYS = frozenset(
    key for key, item in {**_NATIVE_SUMMARY_SPECS, **_SPECIAL_SPECS}.items() if item.get("side") == "left"
)


def specs() -> tuple[NodeSpec, ...]:
    return tuple(_NODE_SPECS.values())


def spec(key: str) -> NodeSpec | None:
    return _NODE_SPECS.get(str(key))


def actions_for_category(category_key: str) -> tuple[ShellAction, ...]:
    category = CATEGORY_BY_KEY.get(str(category_key))
    if category is None:
        return ()
    return tuple(action for _group_title, actions in category.groups for action in actions)


def rail_actions(category_key: str) -> dict[str, list]:
    """分类 → 左右栏内容（全部为 NodeSpec，点击即在画布落节点）。"""
    left: list[NodeSpec] = []
    right: list[NodeSpec] = []
    for action in actions_for_category(category_key):
        node_spec = _NODE_SPECS.get(action.key)
        if node_spec is None:
            continue
        goes_left = (
            node_spec.node_kind in LEFT_RAIL_KINDS
            or node_spec.key in _LEFT_NATIVE_KEYS
            or _CANVAS_SPECS.get(node_spec.key, {}).get("side") == "left"
        )
        if goes_left:
            left.append(node_spec)
        else:
            right.append(node_spec)
    # 每个分类都依赖当前镜头组，空左栏时也给出这一共享数据源。
    lens = _NODE_SPECS.get("lens_editor")
    if lens is not None and not any(item.key == "lens_editor" for item in left):
        left.insert(0, lens)
    # 代理模型训练从数据集开始，把数据管理固定在该分类左栏。
    if str(category_key) == "surrogate":
        data = _NODE_SPECS.get("data")
        if data is not None and not any(item.key == "data" for item in left):
            insert_at = 1 if left and left[0].key == "lens_editor" else 0
            left.insert(insert_at, data)
    # 画布补充节点（MTF / 光强）挂在「光学分析」右栏
    if str(category_key) == "analysis":
        seen = {item.key for item in right}
        for key in ("mtf", "intensity"):
            node_spec = _NODE_SPECS.get(key)
            if node_spec is not None and key not in seen:
                right.append(node_spec)
    return {"left_nodes": left, "right_nodes": right, "left_actions": [], "right_actions": []}


__all__ = [
    "CANVAS_NODE_KEYS",
    "CHART_KIND_BY_KEY",
    "NodeSpec",
    "actions_for_category",
    "rail_actions",
    "spec",
    "specs",
]
