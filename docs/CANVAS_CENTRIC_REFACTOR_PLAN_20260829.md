# 无限画布中心化前端重构技术方案

日期：2026-08-29（v2，纳入「WPS 式工具 tab + 万物可拖拽 + 脏提示」交互形态）
状态：待评审（本文档为方案，不含实施代码）
范围：`frontend_pyside/`（PySide6 桌面前端）；后端 `backend/` 与算法层不动

---

## 1. 背景与目标

当前前端是「导航 rail + 抽屉 + 文档 tab + 页面栈」的传统多页壳层（`app/main_window_layout.py`）。本方案将其重构为**以无限画布为中心**的工作区。

### 1.1 目标界面形态

```
┌──────────────────────────────────────────────────────────┐
│ [系统与建模] [光学分析] [优化] [代理模型] [实验与数据] [教学]   │ ← WPS 式分类 tab
├────┬─────────────────────────────────────────────┬───────┤     （点击只切换工具栏，不跳页）
│镜头│   无限画布（拖拽平移 · Ctrl+滚轮缩放）        │ MTF   │
│组  │                                             │ 光强图 │
│光源│   ┌────────────┐        ┌──────────┐        │ PSF   │
│光纤│   │ 镜头组表格   │───┬───→│ MTF 曲线  │        │ 点列图 │
│计算│   │（可编辑表格） │   │    └──────────┘        │  …    │
│设置│   └────────────┘   │    ┌──────────┐        │       │
│    │                    └───→│ 光强图 ！ │        │       │
│    │                         └──────────┘        │       │
├────┴─────────────────────────────────────────────┴───────┤
│ （左）输入/配置类工具      （中）画布      （右）分析/产出类工具 │
└──────────────────────────────────────────────────────────┘
```

- **开屏即画布**：应用启动直接进入无限画布，无首页/导航跳转概念；
- **顶部分类 tab**：沿用 `compact_shell.CATEGORIES` 六分类（系统与建模 / 光学分析 / 优化 / 代理模型 / 实验与数据 / 教学），点击 tab 只切换左右工具栏内容，**不跳转任何页面**；
- **左右纵向工具栏**：左栏放当前分类的「输入/配置」类工具（镜头组、光源、光纤、计算设置），右栏放「分析/产出」类工具（MTF、光强图、PSF、点列图…）；
- **万物可拖拽**：点击工具即在画布生成对应节点（表格 / 图表 / 面板），所有节点可在画布上任意拖拽、平移、缩放画布视野；
- **依赖与脏提示**：分析图节点绑定数据源节点（如镜头组表格）。数据源被修改后，依赖它的图节点右上角出现「！」徽标；点击「！」可选择**立即更新**、**开启实时更新**或**忽略此版本**；
- **AI 助手**的动作输出同样落到画布节点（创建 / 聚焦 / 高亮）。

### 1.2 非目标

不引入 Web/QtWebEngine 混合架构；不改后端 API 与服务层（`app/bootstrap.py` 组装的服务全部复用）；不改变 viewmodel / context 层职责。

## 2. 技术选型

| 决策点 | 选择 | 理由 |
|---|---|---|
| 画布引擎 | `QGraphicsView` + `QGraphicsScene` | Qt 原生无限画布：世界坐标 qreal（±2^31）、内置视口裁剪、命中检测、LOD、百万级 item 性能。无需自研相机数学。 |
| 功能嵌入 | `QGraphicsProxyWidget` | 把现有 `QWidget` 面板嵌入场景，复用全部现有面板代码与 QSS 主题。 |
| 折叠卡片 | 纯 `QGraphicsItem` 自绘 | 不经过 widget 层，缩放流畅；图标复用 `resources/icons/*.svg`。 |
| 镜头组表格 | `OpticalSystemEditor`（含 `SurfaceTableMixin`）经 proxy 嵌入 | 现成的表面表编辑器，支持曲率/材料/非球面编辑，是「数据源节点」的首个试点。 |
| 脏检测 | 复用 `DirtyScope` + `classify_form_change` | 已有脏分级机制，直接驱动「!」传播。 |
| 结果对账 | 复用 `SimulationResultCache.physical_fingerprint` + `dependency_keys` | 「图过期了吗」= 节点结果指纹与当前项目指纹比对。 |
| 连线 | `QGraphicsPathItem` + 自定义锚点 | 贝塞尔曲线，随节点移动自动重算。 |
| 布局持久化 | `QSettings`（用户级）+ 项目文件（画布文档级） | 相机状态与节点位置分两级存储。 |

与剪映 Web 无限画布的对应：`QGraphicsScene` = 世界坐标系；`QGraphicsView` + `QTransform` = 相机（平移/缩放）；Qt 内置 BSP 索引 + 视口裁剪 = 只渲染可视区。团队无需重新实现相机公式，只需管理「view 的 QTransform ↔ 语义化相机状态」的双向绑定。

### 2.1 性能预算：为什么留在 PySide（先回答「要不要换 React/Vue」）

**结论：性能不是换栈理由。** 数量级论证：

| 维度 | Qt 容量 | 本方案需求 | 裕度 |
|---|---|---|---|
| 轻量画布节点（自绘卡片） | ~100,000 项（BSP 索引 + C++ 视口裁剪） | ~50 个 | ~2000× |
| 同时展开面板（ProxyWidget） | ~25 个（实用上限） | 1–2 个（折叠/展开设计封顶） | ~10× |
| 每帧可视自绘卡片 | ~500 张 | ~30 张 | ~17× |
| 大数组图（PSF/光强/热图） | 一次成像后贴图 | 同左（`fast_heatmap.py` 已实现） | 已达标 |

支撑事实：

- 平移/缩放的逐帧路径在 C++ 内（场景索引、裁剪、变换），Python 不在其中；
- 本项目图表栈已是 `numpy → QImage → QPixmap` 缓存（`shared/plotting/fast_heatmap.py`、`thumbnail_cache.py`），与 Web canvas 高性能是同一套路；个别需要高帧率的曲线可引入 PyQtGraph（同为 Qt 生态）；
- 本方案节流措施（§6.5 的 800ms debounce + 多 view 合并单任务）从需求侧封顶计算频率。

**三条性能红线（实施时作为设计规则执行）**：

1. 同时展开的 proxy 面板封顶 1–2 个（超出即提示折叠其他节点）；
2. 可视自绘卡片超过 ~100 张时，将卡片渲染缓存为 `QPixmap`（`setCacheMode(DeviceCoordinateCache)`），重绘退化为贴图；
3. 大数组图一次成像（QImage），任何重绘只贴缓存图，不重复采样 numpy。

**换栈触发条件（均非性能）**：多人协作 / 云端画布文档（剪映 `canvasId/thread_id` 那层）、浏览器免安装分发、GPU 特效密集场景、团队技术栈整体转向 Web。届时 `NodeSpec` / `CanvasContext` / `CanvasSnapshot` 数据模型可平移到 tldraw / react-flow（§11），且后端已是 HTTP/WS（FastAPI），Web 前端无需重做服务层——但 40+ 面板需要全部重写，属于产品级决策，不进入本方案里程碑。

## 3. 壳层结构设计

### 3.1 主窗口新形态

```
app/
  main_window.py            # 大幅瘦身：顶部 tab 栏 + 左右工具条 + 画布容器 + 浮动按钮
features/canvas/
  view.py                   # CanvasView(QGraphicsView)：相机交互（拖拽平移/滚轮缩放/fit_all）
  scene.py                  # CanvasScene：节点/连线/选择/脏传播
  node.py                   # CanvasNode：折叠卡片 + 展开态 proxy host + 「!」徽标
  node_host.py              # 面板懒加载与生命周期（复用 deferred_page 骨架）
  registry.py               # NodeRegistry：工具 → NodeSpec 映射
  edges.py                  # 数据流连线与锚点
  invalidation_map.py       # DirtyScope → 失效分析种类的映射表
  layout_store.py           # CanvasLayoutStore：布局持久化
  top_tabs.py               # WPS 式分类 tab 栏（CATEGORIES 驱动）
  side_rails.py             # 左右纵向工具条（tab 激活后切换内容）
  minimap.py                # 可选：小地图（二期）
state/canvas_context.py     # CanvasContext：画布文档状态（Qt 信号）
```

### 3.2 顶部 tab 与左右工具条规则

- tab 集合 = `CATEGORIES` 六分类，数据零改动；
- 每个分类下的 `ShellAction` 按 node_kind 分流到左右栏（§4.1）：
  - `source` 类 → 左栏（镜头组、光源、光纤、计算设置、数据管理…）；
  - `view` / `tool` 类 → 右栏（MTF、光强图、PSF、点列图、参数研究、容差…）；
  - 某分类只有单一形态时右栏可隐藏（如「教学」分类全部在左栏弹出式）；
- tab 点击**永不跳页**，只做工具栏内容切换（与 WPS「开始/插入/页面布局」同构）；
- 工具条按钮点击 = 在画布上**创建节点**，落点规则见 §7.3。

### 3.3 现有模块演化

| 现有模块 | 演化方向 |
|---|---|
| `app/page_registry.py` | `PageSpec` → `NodeSpec`（字段同构：key/title/icon/factory_path/lifetime + 新增 node_kind） |
| `app/deferred_page.py` | 降级为节点内容懒加载（`node_host.py` 复用其加载/错误重试骨架） |
| `app/compact_shell.py` | rail/drawer 退役；`ShellAction` 数据结构与 `CATEGORIES` 原样保留，驱动 top_tabs + side_rails |
| `app/main_window.py` | 删除导航栈、文档 tab、页面缓存、reaper；保留命令栏、AI 按钮、工具浮动球 |
| `features/*/page.py` | 整页壳退役；内部面板/lab 拆出为节点可挂载的面板组件 |
| `state/project_context.py`、`task_context.py` | 不动，信号接入画布节点刷新 |
| `features/assistant` | `normalize_action` 输出改由画布消费（创建/聚焦节点），`_TARGET_CONTROLS` 零改动 |

## 4. 节点类型学

画布节点分四类，`NodeSpec.node_kind` 声明：

| node_kind | 内容形态 | 可编辑 | 依赖 | 示例 |
|---|---|---|---|---|
| `source` 数据源节点 | 表格/表单（proxy 嵌入真实编辑器） | 是，编辑产生新版本 | 无（是依赖图的根） | 镜头组表格、光源参数、光纤参数、计算设置 |
| `view` 分析视图节点 | 只读图表（plotting 组件嵌入或自绘） | 否 | 绑定 1 个 source | MTF、光强图、PSF、点列图、相位、模场匹配 |
| `tool` 工具任务节点 | 配置面板 + 提交任务 | 部分参数 | 可绑定 source | 参数研究、容差分析、自动优化、模型训练 |
| `task` 任务状态节点 | 轻量卡片（纯自绘 + 进度） | 否 | 由 tool 派生 | 仿真/扫描/优化/训练任务实时状态 |

规则：

- `view` 节点创建时绑定**当前激活的 source 节点**（最近聚焦/选中的 source）；一个 source 可挂多个 view；一个 view 只绑一个 source；
- 换绑数据源（画布上有多个镜头组节点时）：右键菜单「切换数据源」→ 重新建边并标脏（二期）；
- 折叠态统一为自绘卡片（图标 + 标题 + 即时摘要）；`source` 折叠摘要用 `instant_metrics.estimate_efficiency`（纯前端毫秒级），`view` 折叠摘要显示最近一次结果的关键指标 + 指纹时间。

## 5. 核心接口设计

### 5.1 NodeRegistry

```python
@dataclass(frozen=True, slots=True)
class NodeSpec:
    key: str                  # 继承 ShellAction.key，如 "lens_editor" / "system_view"
    title: str
    icon_name: str            # resources/icons/<icon_name>.svg
    group: str                # 继承 CATEGORIES 分组
    node_kind: str            # source / view / tool / task（左右栏分流 + 依赖规则）
    factory_path: str         # 面板级 widget，如 "features.simulation.components.optical_system_editor:OpticalSystemEditor"
    payload: dict             # 透传面板工厂的初始参数（原 ShellAction.payload）
    analyses: frozenset[str]  # view 节点声明的分析种类（脏传播用，如 {"mtf"}）
    lifetime: str = "cached"  # resident / cached / releasable
    release_after_s: float = 600.0
    summary_provider: str | None = None  # "module:attr" 折叠卡片摘要


class NodeRegistry:
    def specs(self) -> tuple[NodeSpec, ...]: ...
    def spec(self, key: str) -> NodeSpec: ...
    def create_content(self, spec: NodeSpec, payload: dict) -> QWidget: ...
```

### 5.2 CanvasView / CanvasNode / NodeHost

```python
class CanvasView(QGraphicsView):
    zoom: float                       # clamp [0.2, 4.0]
    # 空白拖拽/触控板双指 → 平移；Ctrl+滚轮 → 光标锚定缩放（AnchorUnderMouse）
    def focus_node(self, node_id: str, expand: bool = False): ...
    def fit_all(self): ...
    def reset_camera(self): ...
    # 展开节点时 zoom 动画吸附至 1.0（proxy 非整数缩放文字发虚，§10）

class CanvasNode(QGraphicsObject):
    node_id: str
    spec: NodeSpec
    state: NodeState                  # collapsed / expanded / loading / error / stale
    bound_source_id: str | None       # view/tool 节点绑定的数据源
    def expand(self) / collapse(self): ...
    def refresh(self, hint): ...      # 接 ProjectContext/TaskContext 信号
    def set_stale(self, reason: str, scope: DirtyScope): ...   # 显示「!」
    def clear_stale(self): ...

class NodeHost(QGraphicsProxyWidget):
    contentReady = Signal(str)
    # 复用 deferred_page 的加载占位/工厂调用/错误重试/dispose_widget_tree 骨架
```

### 5.3 CanvasContext

```python
class CanvasContext(QObject):
    nodesChanged = Signal()
    edgesChanged = Signal()
    focusRequested = Signal(str)
    nodeStaleChanged = Signal(str, bool, str)    # node_id, dirty, reason
    def add_node(self, spec_key: str, world_pos: QPointF | None = None) -> str: ...
    def remove_node(self, node_id: str) -> None: ...
    def connect_nodes(self, src: str, dst: str, edge_kind: str = "data") -> None: ...
    def mark_stale(self, source_id: str, scope: DirtyScope, reason: str) -> None: ...
    def refresh_node(self, node_id: str, mode: str = "incremental") -> None: ...
    def snapshot(self) -> CanvasSnapshot / restore(snap): ...
```

### 5.4 布局持久化

1. **用户级（QSettings）**：相机中心 + zoom、折叠偏好；
2. **项目级（跟随项目版本）**：`CanvasSnapshot{nodes: [{key, id, pos, state, bound_source_id, payload}], edges, stale_flags}`，JSON 存项目目录，与 `session_recovery.py` 恢复时序集成。

### 5.5 AI 助手接入

`_handle_assistant_action` 改为：`target_page` + `target_control` → 反查 NodeSpec → 节点已存在则 `focusRequested` + 展开高亮控件；不存在则 `add_node` 后聚焦。`normalize_action` 与 `_TARGET_CONTROLS` 零改动。

## 6. 脏状态传播与「!」交互（本方案核心）

### 6.1 现有底座（零新发明）

| 现有机制 | 位置 | 在画布中的角色 |
|---|---|---|
| `DirtyScope`（ANALYSIS_PLAN / COUPLING / WAVE_PROPAGATION / RAY_TRACE / FULL_SIMULATION） | `simulation/dirty_state.py` | 脏分级：决定「!」传播到哪些图 |
| `classify_form_change(prev, current)` | 同上 | source 节点编辑回调里直接调用 |
| `physical_fingerprint` + `dependency_keys` | `simulation/result_cache.py`（`build_project_dependency_keys`） | view 节点结果与当前输入的对账 |
| `instant_metrics.estimate_efficiency` | `simulation/instant_metrics.py` | 折叠卡片即时摘要（L0 档） |

### 6.2 传播流程

```
source 节点编辑（表格单元格改动）
  → form_state 变化 → classify_form_change → DirtyScope + reason
  → CanvasScene.mark_stale(source_id, scope, reason)
  → 沿依赖边找到下游 view/tool 节点
  → 按 invalidation_map 过滤：只标脏受影响的分析（见 6.3）
  → 受影响节点：state=stale，右上角「!」徽标（含 reason tooltip）
```

**对账兜底**：除事件驱动外，view 节点在恢复布局/切回前台时主动比对 `CachedResult.physical_fingerprint` 与当前项目指纹，不一致即标脏（防止漏事件）。

### 6.3 DirtyScope → 失效分析映射表（初版，评审可调）

| DirtyScope | 触发条件 | 失效的画布节点 |
|---|---|---|
| RAY_TRACE | 光源或系统参数（含镜头组表面）修改 | 光路、点列图、MTF、PSF、光强、相位、焦面、模场匹配 |
| COUPLING | 光纤/五轴参数修改 | 模场匹配、端面匹配、耦合效率类图 |
| WAVE_PROPAGATION | 采样/传播参数修改 | 光束传播、PSF、相位、焦面 |
| ANALYSIS_PLAN | 分析清单修改 | 结果目录节点 |
| FULL_SIMULATION | 其他正式输入修改 | 全部分析节点 |

映射表落在新文件 `canvas/invalidation_map.py`，是纯数据表 + 单测覆盖，物理语义需光学同事评审（§12）。

### 6.4 「!」点击菜单

```
┌ 「!」点击 ──────────────┐
│ ↻ 立即更新               │ → 走 L1/L2（见 6.5）
│ ◉ 实时更新（节点级开关）   │ → 开启后脏即自动刷新（节流）
│ ○ 忽略此版本             │ → 徽标转灰，下次变更再亮
└─────────────────────────┘
```

### 6.5 更新的三档（复用现有计算资产）

| 档 | 触发时机 | 实现 | 延迟量级 |
|---|---|---|---|
| **L0 即时估计** | 输入每次变化（编辑即算） | `instant_metrics`（纯前端）→ 折叠卡片摘要刷新 | 毫秒级 |
| **L1 增量缓存** | 点「!」→ 立即更新 | `SimulationResultCache.missing_analyses(fingerprint, requested)`：命中部分直接重绘，只对缺失部分进入 L2 | 缓存命中即回 |
| **L2 正式计算** | L1 缓存缺失的分析 | 提交后端任务（jobs）→ 任务节点显示进度 → 完成后回填 view 节点 + 更新指纹 | 任务级 |

**实时更新策略**：节点级开关默认关闭（用户显式开启）；开启后 800ms debounce；同一 source 的多个 view 的刷新请求**合并为一个后端任务**（analyses 求并集，cache merge 天然支持增量拼装）。

## 7. 数据流连线与节点放置

### 7.1 连线语义

- `edge_kind` 初期仅 `data`（上游产出 → 下游消费）；
- 连线随节点拖拽实时重算（贝塞尔，锚点在节点左右中点）；
- 下游任一节点 stale 时，对应连线转虚线 + 「!」色提示；刷新完成恢复实线。

### 7.2 自动建边

- 从右栏点「MTF」→ 找当前激活的 source 节点（最近聚焦的镜头组）→ 在其右侧生成 MTF 节点 + 自动建边；
- 依赖链路（参数研究/容差/优化）同样在创建时自动绑定激活 source；
- 一期不做手动拖拽建线（端口拖拽 + 语义校验放二期）。

### 7.3 新节点落点规则

```
候选位置 = 激活 source 右侧固定偏移（如 +240, 0）
         → 若与既有节点包围盒相交，沿 y 方向按 24px 网格步进避让
         → 仍放不下则向 x 方向再进一列
```

落点算法放 `scene.py`，带单测（节点矩形求交 + 网格步进）。

## 8. 迁移里程碑（彻底重构路线）

| # | 里程碑 | 内容 | 验收 |
|---|---|---|---|
| M1 | 画布骨架 + 壳层换装 | `features/canvas` 核心模块；MainWindow 换装：顶部 tab + 左右工具条 + CanvasView；**首个数据源节点：镜头组表格（`OpticalSystemEditor` proxy 嵌入，风险前置试点）**；万物拖拽 + 相机交互 + QSettings 持久化 | 开屏即画布；能添加镜头组表格并编辑表面参数；拖拽/缩放/重启恢复 |
| M2 | 分析节点族 | MTF/光强图/PSF/点列图/相位/模场等 view 节点嵌入（`shared/plotting` 组件）；右栏工具点击创建 + 自动建边 + 落点避让；折叠卡片摘要（L0） | 从右栏点任意分析工具，画布生成对应图节点并连线镜头组 |
| M3 | 脏传播 + 「!」 | `classify_form_change` 接入 source 节点编辑；`invalidation_map`；「!」徽标 + 三选项菜单；L1 增量缓存更新；节点级实时更新（合并 + 节流）；指纹对账兜底 | 修改镜头组 → 仅受影响的图标「!」；点立即更新 → 缓存命中即刷、缺失走任务 |
| M4 | 工具任务节点 + AI | 参数研究/容差/优化/训练的 tool 节点（配置面板 + 提交）；task 节点实时状态（TaskContext 信号）；AI 助手落画布 | 完整研究链路可在画布闭环；AI 动作创建/聚焦节点 |
| M5 | 壳层退役 | 删除 rail / document_tabs / 页面栈 / `PAGE_SPECS` 页面加载；`page_registry` 更名节点注册表；旧 `views/` 清理 | 导航代码删除，画布为唯一中心 |

依赖：M1 → M2 可按分析类型并行；M3 依赖 M2 的 view 节点族；M5 最后（删逃生通道）。

## 9. 任务拆分建议

- **画布核心**（M1）：view/scene/node/edges/layout_store/top_tabs/side_rails，约 8 个新文件；
- **试点嵌入**（M1）：镜头组表格节点 = `OpticalSystemEditor` 构造参数对齐 + NodeSpec 登记；
- **分析节点族**（M2）：每种分析一个 PR（面板导出 + NodeSpec + 摘要 provider）；
- **脏传播**（M3）：`invalidation_map.py` + scene 传播逻辑 + 徽标菜单 + 缓存对账，纯前端可测；
- **助手路由**（M4）：单文件改造（`main_window._handle_assistant_action`）；
- **清理**（M5）：删除清单见 §3.3。

## 10. 风险与规避

| 风险 | 影响 | 规避 |
|---|---|---|
| `QGraphicsProxyWidget` 嵌 `QTableWidget`（镜头组表格）的滚动/单元格编辑事件冲突 | M1 试点即触雷 | **风险前置**：M1 第一个嵌入的就是表格节点；实测不行则镜头组节点改用「画布内卡片 + 点击弹独立编辑窗」混合形态 |
| proxy 非整数缩放文字发虚 | 展开态观感差 | 展开时相机 zoom 动画吸附 1.0；折叠态纯自绘不受影响 |
| 整页 widget 直接嵌入尺寸爆炸 | 画布语义崩坏 | NodeSpec 工厂只接受面板级 widget；评审禁止 `page.py` 整页注册 |
| 实时更新计算风暴（多 view 全开） | 后端压力 | 默认关闭 + 800ms debounce + 同 source 多 view 合并单任务（analyses 并集） |
| `invalidation_map` 物理语义错误 | 「!」漏报/误报 | 映射表纯数据 + 单测；指纹对账兜底防漏；光学同事评审（§12） |
| 多 source 绑定歧义（画布两个镜头组） | 分析图绑错源 | view 创建时绑定「当前激活 source」并在卡片角标显示绑定对象；换绑走右键菜单（二期） |
| 教学模块 QML/3D 节点 | proxy 兼容未知 | 教学节点保持「折叠卡片 + 弹窗打开」混合形态，M4 专项验证 |
| 画布上无地图感，用户迷失 | 可用性 | 相机持久化 + `fit_all` + 顶部 tab 内搜索；minimap 二期 |
| AI 动作误创建重复节点 | 画布噪音 | `add_node` 去重窗口（同 spec + 近距离 + 短时间合并为聚焦） |

## 11. 明确不做 / 后续再议

- 手动拖拽建线手势（二期）；多画布页签/文档多开；
- Web 端复用（NodeSpec/CanvasContext/CanvasSnapshot 数据模型可直接映射 tldraw / react-flow，壳层另做）；
- 协同编辑与云端画布文档（对应剪映 `canvasId/thread_id` 那层，当前无后端需求）；
- 换绑数据源 / 连线语义校验（二期）。

## 12. 评审关注点

1. **顶部 tab 沿用 CATEGORIES 六分类**是否认可，左右栏分流规则（source 左 / view·tool 右）是否符合直觉；
2. **`invalidation_map` 物理正确性**（RAY_TRACE/COUPLING/WAVE_PROPAGATION 各自应失效哪些分析）——需要光学同事逐行确认；
3. **镜头组表格作为 M1 首个试点**（最高风险前置），失败时的混合形态（卡片 + 弹窗编辑）是否可接受；
4. **实时更新默认档位**（建议默认手动 L1，用户显式开启实时）；
5. **CanvasSnapshot 进项目文件**的格式归属（与 `project_repository` 存储约定对齐，需后端评审）。
