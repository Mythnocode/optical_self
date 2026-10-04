# Optical Self 前端 JS / Three.js 迁移完整实施计划

> 项目：`optical_self` / Optical ML Platform  
> 目标：将现有 PySide6 桌面前端迁移为现代 JS 技术栈，并将教学中心 3D 从 Qt Quick 3D 重构为 Three.js。  
> 原则：**后端、光学计算、机器学习核心不重写；迁移的是表现层、交互层和前端状态层。**  
> 建议技术栈：**Electron + Vite + Vue 3 + TypeScript + Pinia + Three.js + FastAPI**。  
> 说明：这里的 TypeScript 仍属于 JS 技术栈；若必须使用纯 JavaScript，可在不改变架构的情况下去掉类型层，但不推荐。

---

## 0. 一页结论

### 0.1 迁移结论

本项目适合迁移到 JS / Electron，但不适合一次性推倒重写。

推荐采用“双前端并行、Python Core 不动、模块逐步替换”的迁移方式：

```text
                         ┌─────────────────────────┐
                         │    optical_core / ML    │
                         │ teaching_runtime / jobs │
                         └────────────┬────────────┘
                                      │
                                  FastAPI / WS
                                      │
                    ┌─────────────────┴─────────────────┐
                    │                                   │
             PySide6 Legacy                      Electron New UI
             用于回归对照                     Vue/TS + Three.js
                    │                                   │
                    └───────────────对照验证─────────────┘
                                      │
                              功能达到门槛后删除旧前端
```

### 0.2 当前工程基线

根据当前项目源码扫描：

| 项目 | 当前规模 |
|---|---:|
| `frontend_pyside` Python | 约 48,225 行 |
| QML | 约 2,216 行 |
| 前端 Python + QML | 约 50,441 行 |
| Teaching V2 相关代码 | 约 8,310 行 |
| `view3d.py` | 1,090 行 |
| `bench_view3d.qml` | 779 行 |
| `model.py` | 1,073 行 |
| `physics.py` | 989 行 |
| `assets.py` | 786 行 |
| `coordinates.py` | 544 行 |
| `teaching_runtime` | 约 1,497 行 |
| FastAPI 后端 | 约 11,041 行 |
| Python 测试 | 41 个测试文件 / 约 6,245 行 |
| `test_teaching_v2_core.py` | 1,531 行 |
| Teaching 3D GLB 资产 | 约 25 个 |

### 0.3 预计工程量

| 目标 | 预计工程量 |
|---|---:|
| 只做 Three.js 教学 3D PoC | 7–12 人日 |
| 新教学中心达到现有核心能力 | 15–25 人日 |
| JS 新前端 MVP | 30–40 人日 |
| 全功能基本替代 PySide | 45–70 人日 |
| 产品级重构 + 体验升级 | 60–90 人日 |

若 1 人全职实施，建议按照 **10–14 周**规划；若 2 人合理拆分，建议按照 **6–9 周**规划。

---

# 1. 项目迁移目标

## 1.1 必须达成

- [ ] 桌面客户端由 Electron 承载。
- [ ] UI 主体迁移到 Web 前端，不再依赖 PySide Widget 作为主界面。
- [ ] Teaching 3D 完全移除 Qt Quick 3D / QML 依赖，使用 Three.js。
- [ ] `optical_core` 保持 Python 实现。
- [ ] `machine_learning` 保持 Python 实现。
- [ ] `teaching_runtime` 保持正式计算实现。
- [ ] FastAPI 成为 JS 前端访问 Python 能力的唯一正式边界。
- [ ] 长任务继续沿用 Job + WebSocket 模式。
- [ ] 当前项目状态、实验参数、场景、任务和结果可持久化。
- [ ] 教学场景的物理语义与现版本一致。
- [ ] 新旧前端可在迁移期间对同一输入进行结果对账。
- [ ] 最终可以打包为 Windows 桌面安装包。

## 1.2 希望同时改善

- [ ] UI 风格统一。
- [ ] 页面之间共享状态更清晰。
- [ ] 3D 操作手感提升。
- [ ] 组件可复用性提升。
- [ ] 前端代码与计算代码彻底解耦。
- [ ] 后续可选择浏览器版，而不需要重写 Python 核心。
- [ ] 为未来无限画布 / 工作流节点化保留扩展接口。

## 1.3 明确不做

第一期不要同时进行下列重写：

- 不把光学求解器改成 WebAssembly。
- 不把机器学习训练改成 JS。
- 不重写 Job Manager。
- 不重写已有正式仿真算法。
- 不同时重构所有数据格式。
- 不在迁移期间修改教学坐标定义。
- 不在迁移期间修改镜子 45° 等物理语义。
- 不为了“代码统一”把 Python 计算搬到 Electron 主进程。
- 不在第一期引入云端账号、多人协作等新产品范围。

---

# 2. 技术选型

## 2.1 推荐技术栈

```text
Desktop
└── Electron
    ├── Main Process
    │   ├── Python backend lifecycle
    │   ├── Native file dialogs
    │   ├── App paths
    │   └── Packaging / update hooks
    │
    ├── Preload
    │   └── 最小化 IPC bridge
    │
    └── Renderer
        ├── Vue 3
        ├── TypeScript
        ├── Vite
        ├── Pinia
        ├── Vue Router
        ├── Three.js
        └── ECharts / Plotly（二选一或按用途组合）

Python
└── FastAPI
    ├── REST
    ├── WebSocket
    ├── optical_core
    ├── optical_runtime
    ├── machine_learning
    └── teaching_runtime
```

## 2.2 为什么不是纯原生 DOM JS

当前前端超过 5 万行，并包含：

- 多工作区；
- 参数编辑器；
- 数据集管理；
- 训练任务；
- 优化任务；
- 结果目录；
- 多分析窗口；
- 教学场景编辑；
- 共享项目状态。

纯原生 DOM JS 可以完成，但状态同步和组件生命周期会快速变复杂。

因此推荐：

> Vue 3 管 UI，Three.js 管 3D，Pinia 管前端状态，FastAPI 管 Python 能力。

## 2.3 为什么推荐 TypeScript

当前工程存在大量强语义字段：

```text
Pose
Component
SceneSnapshot
PhysicsRequest
PhysicsResult
Project
Job
Dataset
Model
ResultManifest
Analysis
```

使用 TS 后可以冻结 API 契约，例如：

```ts
export interface TeachingPose {
  x_mm: number
  y_mm: number
  z_mm: number
  yaw_rad: number
  pitch_rad: number
  roll_rad: number
}
```

避免迁移后出现：

- `mm / um` 混用；
- `deg / rad` 混用；
- `x/y/z` 语义错位；
- `null / undefined` 差异；
- Python snake_case 与 JS camelCase 随意混用。

### 约定

**API JSON 字段统一保留 Python 现有 snake_case。**

不要在前端自动转换成 camelCase，否则对账成本增加。

---

# 3. 目标总体架构

## 3.1 最终结构

```text
optical_self/
│
├── desktop/
│   ├── main/
│   │   ├── main.ts
│   │   ├── backend-manager.ts
│   │   ├── window-manager.ts
│   │   └── app-paths.ts
│   ├── preload/
│   │   └── index.ts
│   └── package.json
│
├── frontend_web/
│   ├── index.html
│   ├── vite.config.ts
│   ├── src/
│   │   ├── main.ts
│   │   ├── App.vue
│   │   │
│   │   ├── app/
│   │   │   ├── router.ts
│   │   │   ├── routes.ts
│   │   │   └── bootstrap.ts
│   │   │
│   │   ├── api/
│   │   │   ├── http.ts
│   │   │   ├── websocket.ts
│   │   │   ├── simulation.ts
│   │   │   ├── datasets.ts
│   │   │   ├── training.ts
│   │   │   ├── models.ts
│   │   │   ├── optimization.ts
│   │   │   ├── jobs.ts
│   │   │   └── teaching.ts
│   │   │
│   │   ├── stores/
│   │   │   ├── project.ts
│   │   │   ├── jobs.ts
│   │   │   ├── datasets.ts
│   │   │   ├── models.ts
│   │   │   ├── teaching.ts
│   │   │   └── ui.ts
│   │   │
│   │   ├── layouts/
│   │   │   └── WorkbenchLayout.vue
│   │   │
│   │   ├── pages/
│   │   │   ├── Home/
│   │   │   ├── Teaching/
│   │   │   ├── Simulation/
│   │   │   ├── Data/
│   │   │   ├── Training/
│   │   │   ├── Models/
│   │   │   ├── Optimization/
│   │   │   ├── Explainability/
│   │   │   └── Tasks/
│   │   │
│   │   ├── teaching/
│   │   │   ├── domain/
│   │   │   │   ├── scene-types.ts
│   │   │   │   ├── coordinates.ts
│   │   │   │   ├── components.ts
│   │   │   │   └── scene-revision.ts
│   │   │   ├── three/
│   │   │   │   ├── TeachingRenderer.ts
│   │   │   │   ├── SceneGraph.ts
│   │   │   │   ├── AssetManager.ts
│   │   │   │   ├── ComponentFactory.ts
│   │   │   │   ├── SelectionManager.ts
│   │   │   │   ├── TransformManager.ts
│   │   │   │   ├── RayLayer.ts
│   │   │   │   ├── CameraController.ts
│   │   │   │   └── GridAndBench.ts
│   │   │   └── components/
│   │   │       ├── TeachingCanvas.vue
│   │   │       ├── ComponentPalette.vue
│   │   │       ├── PropertyInspector.vue
│   │   │       ├── AnalysisPanel.vue
│   │   │       └── ResultPanel.vue
│   │   │
│   │   ├── shared/
│   │   │   ├── components/
│   │   │   ├── charts/
│   │   │   ├── forms/
│   │   │   ├── types/
│   │   │   └── utils/
│   │   │
│   │   └── assets/
│   │       └── teaching/
│   │           └── *.glb
│   │
│   └── tests/
│
├── backend/                  # 保留
├── optical_core/             # 保留
├── optical_runtime/          # 保留
├── machine_learning/         # 保留
├── teaching_runtime/         # 保留
├── shared_contracts/         # 保留/逐步扩展
├── tests/                    # Python 测试继续存在
└── frontend_pyside/          # 迁移完成前保留
```

---

# 4. 迁移边界：什么保留，什么重写

## 4.1 保留不动

| 当前模块 | 策略 |
|---|---|
| `optical_core` | 保留 |
| `optical_runtime` | 保留 |
| `machine_learning` | 保留 |
| `backend/optical_ml_app` | 保留并扩展 API |
| Job Manager | 保留 |
| `/api/v1/*` | 保留 |
| `/ws/jobs` | 保留 |
| `teaching_runtime` | 保留正式物理计算 |
| 用户已有数据 | 保持兼容 |
| GLB 资源 | 直接复用 |

## 4.2 重写

| 当前模块 | 新实现 |
|---|---|
| PySide 主窗口 | Electron + Vue Layout |
| QWidget 页面 | Vue Components |
| Qt Signal UI 通信 | Pinia / composables |
| QSS | CSS / CSS variables |
| QML | Vue + Three.js |
| Qt Quick 3D | Three.js |
| `QQuickWidget` bridge | 删除 |
| 3D MouseArea | Three Raycaster |
| 自制 gizmo 显示 | Three TransformControls + 约束层 |

## 4.3 迁移/拆分

| 当前代码 | 去向 |
|---|---|
| `teaching_v2/model.py` | 前端 SceneStore 类型 + 后端 DTO / 校验 |
| `coordinates.py` | JS 移植一份 + Python 作为权威对账实现 |
| `view3d.py` | Three.js 层重写 |
| `assets.py` | 一部分前端 AssetManager，一部分构建期资产校验 |
| `gizmo.py` | Three TransformControls + 自定义 constraint |
| `physics.py` | 正式计算留 Python；前端仅调用 API |
| `tasks.py` | 合并进统一 Job/Request 状态体系 |
| `inspector.py` | Vue Inspector 重写 |
| `canvas.py` | Vue + Three.js 重写 |

---

# 5. 必须冻结的核心契约

这是本次迁移最重要的一章。

## 5.1 SceneStore 单一状态源

当前 Teaching V2 已明确：

> `SceneStore` 是唯一场景状态源。

新前端继续保持该原则。

不要出现：

```text
Vue Store Pose
Three Object3D Pose
Inspector Local Pose
API Payload Pose
```

四套独立状态。

正确方式：

```text
Pinia TeachingStore
        │
        ├── Inspector
        ├── Three Renderer
        ├── Result status
        └── API serializer
```

Three.js 中的 Object3D 是 SceneStore 的**投影视图**，不是权威数据源。

## 5.2 Pose 内部使用 rad

继续执行当前规则：

```text
内部：rad
界面：deg
```

只有 Inspector 输入/显示边界做换算。

## 5.3 三套坐标系不得合并

### Teaching Bench

```text
x = 导轨方向
y = 横向
z = 台面以上高度
```

### Simulation Engine

```text
Xe = Yt
Ye = Zt - axis_height
Ze = Xt
```

### Three.js Render

沿用当前 view3d 语义：

```text
Xr = Xt
Yr = Zt
Zr = -Yt
```

必须实现：

```ts
teachingToRender()
renderToTeaching()
teachingToEngine()
engineToTeaching()
```

禁止：

```ts
object.position.copy(pose)
```

直接把 Teaching Pose 当 Three 坐标使用。

## 5.4 Scene Revision

任何会改变物理场景的操作：

```text
add
remove
move
rotate
parameter change
enable/disable
```

必须：

```text
revision += 1
```

正式计算结果记录：

```text
result.scene_revision
```

如果：

```text
result.scene_revision !== scene.revision
```

则 UI 必须显示：

```text
过期 / stale
```

不能继续作为当前场景结果使用。

## 5.5 正式计算与几何预览分开

继续保持：

```text
实时拖动
→ geometry preview

用户点击开始计算
→ formal calculation
```

不要拖动 3D 器件时不断调用正式光学引擎。

## 5.6 GLB 锚点语义

当前资产约定：

```text
+X = 光轴
+Z = 上
```

不同器材存在：

```text
出光面
光心
镀膜面
入光面
靶面
```

这些锚点定义必须进入资产 manifest，而不是散落在 Three.js 代码中。

---

# 6. Teaching Three.js 设计

## 6.1 Three.js Scene 分层

建议：

```text
THREE.Scene
│
├── EnvironmentGroup
│   ├── Breadboard
│   ├── Grid
│   ├── Axis guides
│   └── Lighting
│
├── ComponentGroup
│   ├── Laser
│   ├── Lens
│   ├── Fiber
│   └── ...
│
├── HelperGroup
│   ├── Selection outline
│   ├── TransformControls
│   └── measurement guides
│
└── PhysicsOverlayGroup
    ├── preview rays
    ├── formal rays
    └── focus / detector markers
```

## 6.2 Renderer

第一期：

```ts
WebGLRenderer
PerspectiveCamera
OrbitControls
```

后续可加入：

```text
CSS2DRenderer        参数标签
EffectComposer       后处理
OutlinePass          选中描边
FXAA/SMAA            抗锯齿
```

不要一开始就上 Bloom 等视觉特效。

## 6.3 GLB 加载

使用：

```ts
GLTFLoader
```

需要保留现有 `assets.py` 中的思想：

```text
GLB 原始 AABB
    ↓
目标外壳尺寸 HousingSpec
    ↓
缩放 / 锚点偏移
    ↓
Scene Component
```

推荐新增：

```json
{
  "laser": {
    "file": "laser.glb",
    "axis": "+X",
    "up": "+Z",
    "anchor": "output_face",
    "housing_mm": [40, 11, 11]
  }
}
```

例如：

```text
frontend_web/public/assets/teaching/assets-manifest.json
```

## 6.4 缺失资产回退

当前代码已经有“缺 GLB 使用程序几何”的策略。

Three.js 保留：

```text
GLB success
→ GLB

GLB missing / invalid
→ BoxGeometry / CylinderGeometry fallback
```

不能因为一个模型缺失导致教学场景打不开。

## 6.5 选取

使用：

```ts
Raycaster
```

点击流程：

```text
pointerdown
→ normalize device coordinate
→ raycaster.setFromCamera
→ intersectObjects(ComponentGroup)
→ resolve component_id
→ teachingStore.select(id)
```

每个可选 Mesh 应绑定：

```ts
mesh.userData.component_id
```

## 6.6 移动与旋转

使用：

```ts
TransformControls
```

但不能直接让 TransformControls 修改 SceneStore。

推荐流程：

```text
TransformControls drag
        ↓
Three render coordinate
        ↓
renderToTeaching()
        ↓
constraint()
        ↓
Teaching Pose
        ↓
SceneStore.updatePose()
        ↓
revision++
        ↓
renderer rerender
```

## 6.7 约束层

单独创建：

```text
TransformConstraintService
```

职责：

- 限制器件不能沉入台面；
- 可配置只允许沿 x；
- 支持 y/z 微调；
- 支持旋转轴限制；
- 支持 snap；
- 防止非法 NaN/Infinity；
- 不让 View3D 坐标写回 Pose。

## 6.8 Ray 渲染

物理结果统一转换为：

```ts
interface RaySegment {
  start_teaching_mm: [number, number, number]
  end_teaching_mm: [number, number, number]
  power_fraction?: number
}
```

Three.js：

```text
Teaching coordinate
→ teachingToRender
→ BufferGeometry
→ Line / LineSegments
```

光线分两层：

```text
previewRayLayer
formalRayLayer
```

正式结果过期后：

- 可以保留显示，但必须视觉标记 stale；或
- 默认隐藏，用户可打开“显示旧结果”。

第一期建议默认隐藏旧正式结果。

## 6.9 相机模式

至少保留：

- [ ] Perspective 透视模式；
- [ ] Top 顶视模式；
- [ ] Front / Side 快捷视角；
- [ ] Fit Scene；
- [ ] Focus Selected；
- [ ] Reset Camera。

---

# 7. Teaching API 改造

## 7.1 为什么必须增加 Teaching API

当前 Teaching 前端 Python 可以直接访问 Python runtime。

JS 无法直接：

```python
from teaching_runtime import ...
```

所以需要通过 FastAPI 暴露。

## 7.2 推荐 API

### 获取教学配置

```http
GET /api/v1/teaching/catalog
```

### 检查场景

```http
POST /api/v1/teaching/inspect
```

### 几何预览

```http
POST /api/v1/teaching/preview
```

如果几何预览纯前端足够快，也可以在前端实现近似预览；但 Python 版本继续作为对账基准。

### 正式计算

推荐沿用统一 Job 体系：

```http
POST /api/v1/teaching/jobs
```

请求：

```json
{
  "scene": {},
  "scene_revision": 12,
  "analysis": "raytrace"
}
```

返回：

```json
{
  "job_id": "job-xxx",
  "status": "queued"
}
```

状态继续走：

```text
/ws/jobs
```

结果继续通过：

```http
GET /api/v1/jobs/{job_id}
GET /api/v1/jobs/{job_id}/result
```

## 7.3 Teaching DTO

后端新增 Pydantic Models：

```text
TeachingPoseDTO
TeachingComponentDTO
TeachingSceneDTO
TeachingComputeRequest
TeachingComputeResult
```

不让 FastAPI Route 直接吃任意 `dict`。

## 7.4 版本字段

所有 Teaching Request 必须带：

```json
{
  "schema_version": "1",
  "scene_revision": 12
}
```

正式返回带：

```json
{
  "schema_version": "1",
  "scene_revision": 12,
  "source": "formal"
}
```

---

# 8. 前端共享状态设计

## 8.1 Stores

### Project Store

```text
project_id
project_version
physical parameters
simulation payload
dirty scopes
```

### Job Store

```text
jobs
activeJobs
progress
status
result summary
```

### Teaching Store

```text
scene
revision
selected_component_id
preview_result
formal_results
camera_state
ui_state
```

### Dataset Store

```text
datasets
active_dataset
import state
```

### Model Store

```text
models
active_model
prediction
explainability state
```

## 8.2 哪些状态不能放 Store

下列属于 Three.js 内部运行态：

```text
WebGLRenderer
Scene
Camera
OrbitControls
TransformControls
Raycaster
Texture
GLTF cache
```

这些不能直接放 Pinia 进行响应式代理。

应由：

```text
TeachingRenderer class
```

持有。

---

# 9. 现有模块迁移映射

根据当前 `shell_catalog.py`，建议按照下面方式迁移。

## 9.1 系统与建模

现有：

```text
项目总览
系统建模
完整镜头编辑器
计算设置
```

新前端：

```text
pages/Simulation/SystemEditor
pages/Simulation/LensEditor
pages/Simulation/ComputeSettings
```

优先把表单数据结构迁出 QWidget，不要先追求视觉复刻。

## 9.2 光学分析

现有：

```text
系统视图
光束传播
焦面分析
复光场
模场匹配
像质与波前
完整结果目录
参数研究
容差分析
```

迁移重点：

- 分析选择 → API 参数；
- Job 提交；
- Job 结果解包；
- 绘图；
- 结果 stale / fingerprint。

## 9.3 优化

现有：

```text
自动优化
物理反向设计
ML 反向预测
```

后端已有 `/optimization/jobs`，因此主要是 UI 和 payload 迁移。

## 9.4 代理模型 / Machine Learning

现有：

```text
随机森林
XGBoost 物理残差
BiLSTM
模型构建
正向预测
模型解释
模型管理
```

后端已有：

```text
/training/jobs
/training/joint/jobs
/models
/models/{id}/predict
/models/{id}/shap/*
/structure-models/*
```

这里属于相对低风险迁移。

## 9.5 实验与数据

现有：

```text
数据管理
任务中心
```

已有 API，可以较早迁移，用来验证新 API Client 和 Job Store。

## 9.6 教学

Teaching 是整个迁移中独立工作包，优先做 PoC，但完整替换安排在中期。

---

# 10. 分阶段实施路线

---

## Phase 0：冻结基线与建立迁移测试

**目标：不改行为，先明确什么叫“迁移正确”。**

预计：2–4 人日。

### 工作

- [ ] 当前主分支打 migration baseline tag。
- [ ] 运行全部 Python tests 并记录结果。
- [ ] 记录当前应用版本 `1.5.6`。
- [ ] 导出 FastAPI OpenAPI schema。
- [ ] 记录主要页面截图。
- [ ] 记录 Teaching 标准场景 JSON。
- [ ] 记录 Teaching 标准场景正式结果。
- [ ] 记录坐标转换 golden cases。
- [ ] 记录 GLB inventory / AABB。
- [ ] 记录仿真标准输入/输出。
- [ ] 记录训练、优化最小 smoke case。

### Golden Cases

至少建立：

```text
GC-T01 Teaching empty scene
GC-T02 laser + lens + fiber
GC-T03 laser + mirror
GC-T04 lens rotation
GC-T05 fiber lateral offset
GC-S01 basic simulation
GC-J01 job progress
GC-D01 dataset list/import
GC-M01 model list/predict
GC-O01 optimization submit/result
```

### 验收

- [ ] Golden 文件进入 `tests/golden/`。
- [ ] 所有人可以一条命令跑 baseline tests。
- [ ] 迁移过程中不得随意修改 golden，修改必须说明原因。

---

## Phase 1：建立 Electron + Vite + Vue 基础工程

预计：3–5 人日。

### 工作

- [ ] 初始化 `frontend_web`。
- [ ] 初始化 `desktop`。
- [ ] Vite dev server。
- [ ] Electron dev 启动。
- [ ] Electron preload。
- [ ] renderer 禁止直接 Node integration。
- [ ] CSS variables / theme tokens。
- [ ] Router。
- [ ] Pinia。
- [ ] error boundary。
- [ ] toast / modal / loading 基础组件。

### Electron 安全配置

```text
nodeIntegration: false
contextIsolation: true
sandbox: true（可行时）
```

不要把整个 `fs` 暴露给 Renderer。

### 验收

- [ ] `npm run dev` 可启动。
- [ ] Electron 能打开 renderer。
- [ ] 前端能请求 `/api/v1/health`。
- [ ] Python backend 不启动时能显示清晰错误。

---

## Phase 2：Python Backend 生命周期接管

预计：2–4 人日。

### 目标

Electron 能可靠启动 / 检测 / 关闭本地 FastAPI。

### Backend Manager

```text
App start
  ↓
check 127.0.0.1:8000 health
  ↓
not running
  ↓
spawn Python backend
  ↓
wait /health
  ↓
renderer ready
```

### 必须处理

- [ ] 端口冲突；
- [ ] Python process 意外退出；
- [ ] Electron 退出清理；
- [ ] backend log；
- [ ] 开发模式与打包模式路径差异；
- [ ] Windows spawn；
- [ ] 用户数据路径。

### 验收

- [ ] 连续启动关闭 20 次无残留进程。
- [ ] backend crash 有错误页面。
- [ ] 端口冲突有明确提示。

---

## Phase 3：统一 JS API Client + Job Store

预计：3–5 人日。

### 目标

先打通平台最核心的“提交任务 → 看进度 → 取结果”。

### 实现

```text
api/http.ts
api/websocket.ts
stores/jobs.ts
```

API Client 支持：

- [ ] timeout；
- [ ] request id；
- [ ] JSON error；
- [ ] retry policy；
- [ ] cancellation；
- [ ] base URL；
- [ ] dev logging。

WebSocket 支持：

- [ ] reconnect；
- [ ] ping/pong；
- [ ] job event dispatch；
- [ ] duplicate event tolerance。

### 验收

新前端可以：

```text
提交 simulation job
→ 实时显示 progress
→ 完成
→ 拉结果
```

这一步完成后，说明 JS 前端与现后端的主链路成立。

---

## Phase 4：Teaching Three.js 技术验证 PoC

预计：7–12 人日。

### 只做一个独立页面

不要立刻迁整个 Teaching UI。

### PoC 必须完成

- [ ] Three Scene / Camera / Light。
- [ ] Breadboard。
- [ ] 加载 `laser.glb`。
- [ ] 加载 `lens.glb`。
- [ ] 加载 `fiber.glb`。
- [ ] `Teaching → Render` 坐标转换。
- [ ] Raycaster 选择。
- [ ] TransformControls x/y/z 移动。
- [ ] Three → Teaching 回写。
- [ ] Scene revision。
- [ ] preview ray。
- [ ] camera orbit。
- [ ] 顶视图。

### 核心验收

同一个 Pose：

```text
Python snapshot_to_render_nodes
```

与：

```text
JS teachingToRender
```

输出位置与方向必须在容差范围一致。

### Go / No-Go

PoC 结束必须评审：

- GLB 是否正常；
- 坐标是否一致；
- TransformControls 是否能满足教学约束；
- GPU 性能是否正常；
- Three.js 是否值得全面替换。

理论上这里应得到 Go。

---

## Phase 5：完整 Teaching Scene Domain 迁移

预计：5–8 人日。

### 迁移 `model.py`

前端创建：

```text
scene-types.ts
component-catalog.ts
scene-serializer.ts
scene-validator.ts
```

迁移：

- [ ] ComponentKind；
- [ ] default params；
- [ ] PLACEABLE_KINDS；
- [ ] Pose；
- [ ] Component；
- [ ] Scene；
- [ ] revision；
- [ ] selection；
- [ ] JSON load/save；
- [ ] reserved id rules。

### 注意

不要照抄 Python QObject / Signal。

只迁移“领域语义”，不要迁 Qt 实现。

---

## Phase 6：Teaching 资产系统迁移

预计：3–5 人日。

### 工作

- [ ] 建 assets manifest。
- [ ] GLTF cache。
- [ ] AABB 读取。
- [ ] Housing target fit。
- [ ] anchor correction。
- [ ] stem generation。
- [ ] fallback geometry。
- [ ] missing asset diagnostics。

### 性能要求

GLB 必须缓存：

```text
load once
clone many
```

建议使用 `SkeletonUtils.clone`（存在骨骼时）或安全深克隆策略。

当前模型主要为静态器材，可采用共享 geometry/material + Object3D clone。

---

## Phase 7：Teaching Inspector / Palette / 交互迁移

预计：4–7 人日。

### Palette

支持当前可添加类型：

```text
laser
isolator
waveplate
lens
cylindrical_lens
beam_expander
aperture
pbs
splitter
beam_sampler
grating
mirror
fiber
ccd
power_meter
wavefront_sensor
oscilloscope
```

### Inspector

- [ ] label；
- [ ] enabled；
- [ ] xyz；
- [ ] yaw/pitch/roll；
- [ ] kind-specific params；
- [ ] 单位；
- [ ] 输入限制；
- [ ] optional unset；
- [ ] invalid input handling。

### UI 操作

- [ ] 新增；
- [ ] 删除；
- [ ] 复制；
- [ ] 拖动；
- [ ] 旋转；
- [ ] 锁定；
- [ ] reset pose；
- [ ] focus selected。

---

## Phase 8：Teaching 正式计算 API 化

预计：3–6 人日。

### 后端

新增：

```text
routes_teaching.py
teaching_models.py
teaching_service_adapter.py
```

接：

```text
teaching_runtime
```

### 分析类型

至少覆盖现有：

```text
geometry
raytrace
spot
field
coupling
wavefront
```

### 前端

- [ ] 开始计算；
- [ ] running；
- [ ] elapsed；
- [ ] warning；
- [ ] error；
- [ ] source；
- [ ] stale；
- [ ] result tabs。

### 验收

相同标准场景：

```text
PySide Teaching result
```

和：

```text
Electron Teaching result
```

必须来自同一 Python runtime，并输出一致。

---

## Phase 9：Teaching 完整替换验收

预计：2–4 人日。

### 必测

- [ ] 场景创建；
- [ ] 全部 kind 添加；
- [ ] GLB 加载；
- [ ] 缺 GLB fallback；
- [ ] 旋转；
- [ ] translation；
- [ ] 三坐标转换；
- [ ] mirror convention；
- [ ] CCD alias；
- [ ] fiber offsets；
- [ ] formal rays；
- [ ] coupling；
- [ ] stale result；
- [ ] JSON save/load；
- [ ] resize；
- [ ] 4K / high DPI。

### 完成定义

Teaching 新版通过后，PySide Teaching 进入 freeze：

> 不再新增功能，只接受 blocker bug fix。

---

# 11. 非 Teaching 模块迁移顺序

推荐顺序不是按菜单顺序，而是按风险从低到高。

## 11.1 第一批：数据管理 + 任务中心

预计：4–6 人日。

原因：API 边界清晰，适合验证基础组件。

完成：

- 数据集列表；
- 数据导入；
- manifest；
- jobs table；
- progress；
- retry/cancel；
- result summary。

## 11.2 第二批：模型管理 + 预测

预计：4–6 人日。

- models list；
- model detail；
- predict；
- BiLSTM predict；
- model adoption/version display。

## 11.3 第三批：训练

预计：4–6 人日。

- random forest；
- XGBoost residual；
- BiLSTM；
- joint training；
- training result。

## 11.4 第四批：Explainability

预计：3–5 人日。

- SHAP；
- design variables；
- global contribution；
- parameter trend；
- current system explanation。

## 11.5 第五批：Optimization

预计：4–7 人日。

- variables；
- optimization submit；
- progress；
- candidates；
- formal verify；
- result comparison。

## 11.6 最后：Simulation 主工作区

预计：8–14 人日。

Simulation 最复杂，最后迁移。

包括：

- system editor；
- surface table；
- material library；
- compute settings；
- simulation payload；
- system view；
- propagation；
- PSF；
- field；
- coupling；
- wavefront；
- result catalogue；
- parameter research；
- tolerance。

---

# 12. Simulation 重构策略

## 12.1 不逐 Widget 翻译

错误方式：

```text
QWidget A → Vue A
QWidget B → Vue B
QWidget C → Vue C
```

推荐先整理数据结构：

```text
Project State
    ↓
Simulation Request Compiler
    ↓
API
    ↓
Simulation Result
    ↓
View Models
    ↓
Charts
```

## 12.2 Surface Table

这是高价值组件，应独立设计：

```text
OpticalSurfaceTable.vue
```

要求：

- 虚拟滚动（如果未来表面很多）；
- cell validation；
- keyboard editing；
- copy/paste；
- material selector；
- units；
- dirty state；
- undo/redo。

第一期可以暂不做完整 Excel 体验，但数据层必须稳定。

## 12.3 结果图

建议：

```text
普通二维统计/曲线 → ECharts
科研二维/三维结果 → Plotly 或自定义 Canvas/WebGL
教学 3D → Three.js
```

不要用 Three.js 统一所有图。

---

# 13. 前端视觉系统

## 13.1 Design Tokens

统一：

```css
--bg-primary
--bg-secondary
--surface
--surface-hover
--text-primary
--text-secondary
--border
--accent
--success
--warning
--danger
--radius-sm
--radius-md
--shadow-panel
--space-1 ...
```

## 13.2 不直接搬 QSS

QSS 只用于参考视觉，不按行翻译。

建立：

```text
Button
IconButton
Panel
Card
FormRow
NumberInput
Select
Tabs
Toolbar
StatusBadge
Progress
DataTable
PlotPanel
```

基础组件后再做业务页面。

---

# 14. 文件与项目持久化

## 14.1 文件操作边界

Renderer 不直接访问 Node `fs`。

流程：

```text
Renderer
→ preload IPC
→ Electron Main
→ fs / native dialog
```

## 14.2 项目格式

短期：保持现有格式兼容。

不要在迁移同时更换整个 project schema。

新字段采用：

```json
{
  "schema_version": 2
}
```

并保留 migration function。

## 14.3 Teaching JSON

Teaching scene 单独做：

```text
parse
validate
migrate
serialize
```

必须可读取旧版 PySide Teaching JSON。

---

# 15. 测试策略

## 15.1 Python Tests 保留

现有 41 个 Python 测试文件继续作为核心层防线。

不要因为前端迁移删除。

## 15.2 JS Unit Tests

推荐：

```text
Vitest
```

重点测试：

```text
coordinates
scene revision
serializer
dirty logic
payload builder
result parser
asset manifest
constraint math
```

## 15.3 Three.js 测试

Three.js 的 GPU 视觉不要全部用 unit test。

数学和 scene graph 用 unit test；真实画面使用：

```text
Playwright screenshot regression
```

## 15.4 E2E

推荐：

```text
Playwright + Electron
```

至少：

```text
E2E-01 启动应用
E2E-02 backend health
E2E-03 Teaching add/move lens
E2E-04 Teaching compute
E2E-05 Simulation submit
E2E-06 Job progress
E2E-07 Dataset list
E2E-08 Model predict
E2E-09 Optimization
E2E-10 Project save/reopen
```

## 15.5 双端对账

迁移期间建立：

```text
same payload
   ├── PySide frontend
   └── JS frontend

→ compare backend request
→ compare backend result
```

不是比较像素，而是优先比较“输入与结果”。

---

# 16. 性能预算

## 16.1 Teaching 3D

目标：

| 指标 | 目标 |
|---|---:|
| 常规场景 FPS | ≥ 60 FPS（典型设备） |
| 拖动最低 FPS | ≥ 45 FPS |
| 3D 首次可交互 | ≤ 2 s（本地资产） |
| selection latency | < 50 ms |
| Inspector → 3D 更新 | 一帧内 |

## 16.2 Three.js 优化顺序

只有出现问题再做：

1. GLB cache；
2. shared geometry/material；
3. 减少 shadow caster；
4. 限制 pixelRatio；
5. requestAnimationFrame only when dirty（非持续动画场景）；
6. instancing（大量同类对象才需要）；
7. asset compression。

不要 PoC 阶段提前优化。

## 16.3 图表

大数组：

```text
Python 计算
→ compact numeric result / image artifact
→ JS display
```

避免把超大中间数组无脑塞 JSON。

---

# 17. 打包方案

## 17.1 开发模式

```text
npm run dev
├── Vite
├── Electron
└── Python FastAPI
```

## 17.2 生产模式

推荐：

```text
Electron bundle
├── renderer dist
├── Python runtime
├── backend source / frozen executable
├── optical core
├── ML runtime
└── assets
```

### 两种 Python 打包方案

#### A. 内置 Python 环境

优点：兼容性最好。  
缺点：安装包大。

#### B. PyInstaller/Nuitka 后端可执行文件

优点：用户无需 Python。  
缺点：科学计算依赖打包与动态库验证工作较多。

### 建议

第一阶段先用 **内置隔离 Python 环境** 完成迁移。

迁移稳定后再做 PyInstaller/Nuitka。

不要同时处理“前端换栈”和“Python 冻结打包”两个大变量。

---

# 18. 日志与诊断

必须保留三类日志：

```text
Electron main log
Frontend renderer log
Python backend log
```

每次 API 请求记录：

```text
request_id
route
status
elapsed
job_id（有时）
```

前端错误页提供：

```text
复制诊断信息
打开日志目录
重新连接后端
```

---

# 19. 风险清单

## R1：坐标系迁移错误

风险：★★★★★

表现：

- 画面看似正常，但正式引擎接收到错误方向；
- mirror / fiber 结果异常；
- 拖动后回跳。

措施：

- Python/JS 双实现 golden tests；
- 坐标函数独立模块；
- 禁止组件中手写轴交换。

## R2：SceneStore 出现双状态

风险：★★★★★

措施：

- Pinia Scene 为唯一源；
- Three Object3D 只做投影；
- TransformControls 最终必须经过 Store action。

## R3：正式计算被 UI 逻辑污染

风险：★★★★★

措施：

- JS 不实现正式物理；
- Python runtime 权威；
- API contract tests。

## R4：Big Bang 导致长期不可用

风险：★★★★★

措施：

- PySide 不删除；
- 按模块切；
- 每阶段有独立完成定义。

## R5：Electron 打包科学计算依赖困难

风险：★★★★☆

措施：

- 打包后端放到后期；
- 开发期先 spawn 当前 Python。

## R6：Three.js 视觉重构无限扩张

风险：★★★★☆

措施：

第一阶段禁止：

```text
Bloom
复杂粒子
高级材质编辑器
动画系统
实时 GI
```

先实现正确性。

## R7：新 UI 功能范围持续增加

风险：★★★★☆

迁移和新产品功能分开 issue。

规则：

```text
Migration issue = 旧功能等价
Enhancement issue = 新功能
```

---

# 20. Git 分支策略

推荐：

```text
main
├── migration/js-shell
├── migration/teaching-three
├── migration/api-teaching
├── migration/simulation
├── migration/ml
└── migration/packaging
```

不要维持一个几个月不合并的 mega branch。

## 提交规范

```text
feat(web): ...
feat(three): ...
feat(api): ...
fix(three): ...
test(migration): ...
refactor(web): ...
chore(packaging): ...
```

---

# 21. 推荐人员分工

## 两人配置

### A：Web / Three.js

负责：

- Electron renderer；
- Vue；
- Pinia；
- Three.js；
- Teaching UI；
- charts；
- E2E。

### B：Python / Integration

负责：

- FastAPI；
- Teaching endpoints；
- DTO；
- Job integration；
- project persistence；
- Python tests；
- packaging backend。

共同：

- coordinate contract；
- golden tests；
- acceptance。

## 三人配置

第三人重点负责：

- Simulation / ML 页面迁移；
- Design System；
- charts；
- Playwright 回归。

---

# 22. 推荐 10 周里程碑

这是一个两人左右配置的参考计划，不是死日期。

| 周 | 主要目标 | 可见成果 |
|---|---|---|
| W1 | Phase 0–2 | Electron 能启动 Python backend |
| W2 | Phase 3 + Three PoC | 新前端能跑 Job；3D 能显示器材 |
| W3 | Teaching Scene / GLB / Controls | 可添加、选择、移动、旋转 |
| W4 | Teaching API + 正式计算 | Three 教学能算 raytrace / coupling |
| W5 | Teaching 完整验收 + Data/Jobs | 教学中心可作为新入口使用 |
| W6 | Models / Training | ML 主链路可用 |
| W7 | Optimization / Explainability | ML 后半链路可用 |
| W8 | Simulation Editor | 系统编辑 + 提交正式仿真 |
| W9 | Simulation Results | 核心分析视图可用 |
| W10 | Packaging / regression | Release Candidate |

若 1 人做，按 10 周直接执行会太紧，建议拉长至 12–16 周。

---

# 23. 每阶段退出标准 Definition of Done

一个模块不是“页面看起来做完了”就算完成。

必须满足：

- [ ] 核心功能可操作；
- [ ] API error 可见；
- [ ] loading 可见；
- [ ] empty state 可见；
- [ ] stale state 正确；
- [ ] 数据保存恢复；
- [ ] unit tests；
- [ ] 至少一条 E2E；
- [ ] 和 PySide baseline 对账；
- [ ] 没有新增直接 Python import 的 renderer 代码；
- [ ] 没有 renderer 直接 Node fs；
- [ ] 无已知 blocker。

---

# 24. PySide 删除条件

不要按时间删除 PySide。

满足下面所有条件再删除：

- [ ] Teaching 完整替代；
- [ ] Simulation 核心工作流完整；
- [ ] Data / Training / Model 完整；
- [ ] Optimization 完整；
- [ ] Explainability 完整；
- [ ] Job Center 完整；
- [ ] 项目保存/打开完整；
- [ ] Windows 打包稳定；
- [ ] 新版连续完成至少一轮完整回归；
- [ ] Golden cases 全通过；
- [ ] 正式计算结果无差异；
- [ ] 新版成为默认入口至少一个版本周期。

然后：

```text
run_frontend.py
frontend_pyside/
PySide6
QML
Qt Quick 3D
```

才进入删除阶段。

---

# 25. 具体 WBS 任务表

## Epic A：基础设施

- [ ] A01 创建 `frontend_web/`
- [ ] A02 创建 `desktop/`
- [ ] A03 配置 Vite
- [ ] A04 配置 Electron
- [ ] A05 配置 TS
- [ ] A06 配置 Vue Router
- [ ] A07 配置 Pinia
- [ ] A08 配置 Vitest
- [ ] A09 配置 Playwright
- [ ] A10 设计 CSS Tokens

## Epic B：Backend Bridge

- [ ] B01 Health client
- [ ] B02 Electron backend manager
- [ ] B03 process lifecycle
- [ ] B04 backend logs
- [ ] B05 API error parser
- [ ] B06 WebSocket reconnect
- [ ] B07 Job store
- [ ] B08 result loader

## Epic C：Teaching Domain

- [ ] C01 Teaching types
- [ ] C02 ComponentKind
- [ ] C03 default params
- [ ] C04 Pose validation
- [ ] C05 Scene Store
- [ ] C06 revision
- [ ] C07 serializer
- [ ] C08 old JSON migration
- [ ] C09 coordinate conversion
- [ ] C10 coordinate golden tests

## Epic D：Teaching Three.js

- [ ] D01 Renderer lifecycle
- [ ] D02 Camera
- [ ] D03 OrbitControls
- [ ] D04 lights
- [ ] D05 breadboard
- [ ] D06 GLTFLoader
- [ ] D07 asset manifest
- [ ] D08 AABB fit
- [ ] D09 fallback geometry
- [ ] D10 ComponentFactory
- [ ] D11 Raycaster selection
- [ ] D12 TransformControls translate
- [ ] D13 TransformControls rotate
- [ ] D14 coordinate write-back
- [ ] D15 constraints
- [ ] D16 selection outline
- [ ] D17 ray preview
- [ ] D18 formal ray layer
- [ ] D19 top view
- [ ] D20 fit/focus camera

## Epic E：Teaching UI

- [ ] E01 ComponentPalette
- [ ] E02 PropertyInspector
- [ ] E03 scene toolbar
- [ ] E04 analysis controls
- [ ] E05 result panel
- [ ] E06 warnings
- [ ] E07 stale badge
- [ ] E08 save/load scene
- [ ] E09 error states

## Epic F：Teaching Backend

- [ ] F01 Teaching Pydantic models
- [ ] F02 `GET /teaching/catalog`
- [ ] F03 `POST /teaching/inspect`
- [ ] F04 preview endpoint（若需要）
- [ ] F05 formal teaching job
- [ ] F06 result mapper
- [ ] F07 error mapper
- [ ] F08 API contract tests

## Epic G：Data / Jobs

- [ ] G01 Dataset list
- [ ] G02 Dataset import
- [ ] G03 Dataset detail
- [ ] G04 Job list
- [ ] G05 Job detail
- [ ] G06 cancel
- [ ] G07 retry

## Epic H：ML

- [ ] H01 Models list
- [ ] H02 Predict
- [ ] H03 RF training
- [ ] H04 XGBoost residual
- [ ] H05 BiLSTM
- [ ] H06 Training result
- [ ] H07 SHAP

## Epic I：Optimization

- [ ] I01 variable editor
- [ ] I02 submit optimization
- [ ] I03 progress
- [ ] I04 result table
- [ ] I05 candidate verification
- [ ] I06 inverse design

## Epic J：Simulation

- [ ] J01 project store
- [ ] J02 source parameters
- [ ] J03 surface table
- [ ] J04 material selector
- [ ] J05 compute settings
- [ ] J06 payload compiler
- [ ] J07 submit simulation
- [ ] J08 system view
- [ ] J09 propagation
- [ ] J10 PSF
- [ ] J11 field
- [ ] J12 coupling
- [ ] J13 wavefront
- [ ] J14 result catalogue
- [ ] J15 parameter research
- [ ] J16 tolerance

## Epic K：Packaging

- [ ] K01 production renderer build
- [ ] K02 backend path resolve
- [ ] K03 user_data location
- [ ] K04 Windows packaging
- [ ] K05 icon/version metadata
- [ ] K06 installer
- [ ] K07 clean machine test

## Epic L：Decommission

- [ ] L01 switch default launcher
- [ ] L02 PySide read-only freeze
- [ ] L03 remove QML dependency
- [ ] L04 remove PySide package dependency
- [ ] L05 archive old frontend docs
- [ ] L06 remove old frontend after release gate

---

# 26. 第一阶段推荐实际开工顺序

不要从“把首页做漂亮”开始。

建议严格按下面顺序：

```text
1. FastAPI health
2. Electron backend lifecycle
3. JS API client
4. Job WebSocket
5. Three Scene
6. teaching coordinates
7. laser/lens/fiber GLB
8. selection
9. TransformControls
10. SceneStore
11. Teaching Inspector
12. Teaching formal API
13. Teaching result
14. Dataset/Job UI
15. ML
16. Optimization
17. Simulation
18. Packaging
```

这个顺序优先验证架构风险，而不是优先完成视觉效果。

---

# 27. 第一批代码建议

第一次提交只创建骨架，不搬业务：

```text
frontend_web/
  src/
    api/http.ts
    api/websocket.ts
    stores/jobs.ts
    pages/DevBackendPage.vue
    pages/Teaching/ThreePoc.vue
    teaching/domain/coordinates.ts
    teaching/three/TeachingRenderer.ts

desktop/
  main/backend-manager.ts
  main/main.ts
  preload/index.ts
```

第一阶段页面甚至可以很丑，只需要显示：

```text
Backend: Connected
API version: 1.5.6
Jobs WS: Connected
Three.js: 60 FPS
Teaching coordinates: PASS
laser.glb: OK
lens.glb: OK
fiber.glb: OK
```

这页全部通过之后再开始正式 UI。

---

# 28. 推荐的迁移验收矩阵

| 能力 | PySide | JS MVP | JS Final |
|---|---:|---:|---:|
| Backend health | ✓ | ✓ | ✓ |
| Jobs | ✓ | ✓ | ✓ |
| Teaching 3D | Qt Quick 3D | Three.js | Three.js |
| Teaching formal physics | ✓ | ✓ | ✓ |
| Scene revision | ✓ | ✓ | ✓ |
| GLB | ✓ | ✓ | ✓ |
| Dataset | ✓ | ✓ | ✓ |
| Model prediction | ✓ | ✓ | ✓ |
| Training | ✓ | △ | ✓ |
| Optimization | ✓ | △ | ✓ |
| Simulation editor | ✓ | 核心 | ✓ |
| All result views | ✓ | 部分 | ✓ |
| Project persistence | ✓ | ✓ | ✓ |
| Windows package | PySide | dev | ✓ |

---

# 29. 对现有工程的特殊注意事项

## 29.1 当前后端已经具备迁移基础

FastAPI 目前已经把主要路由挂载到：

```text
/api/v1
```

并已有：

```text
/simulation/jobs
/jobs
/dataset/jobs
/headless-datasets
/training/jobs
/models
/structure-models
/tolerance/jobs
/scan/jobs
/optimization/jobs
/verification
/validation
/ws/jobs
```

因此不需要重新设计整个平台通信架构。

## 29.2 前端直接依赖核心代码并不多

当前 `frontend_pyside` 中显式直接 import 核心计算包的地方较少，这意味着现有工程已经具备一定 API 隔离度。

需要逐个消除剩余直接依赖，例如：

```text
simulation/material_library.py → optical_core.materials
workbench_payloads.py → machine_learning splitter helper
```

原则：

> 新 JS Renderer 不得复制这种直接依赖模式。

需要的数据通过：

```text
API / shared contract / static catalog
```

提供。

## 29.3 Teaching 当前设计本身值得保留

现有 Teaching V2 已经明确建立：

- 单一 SceneStore；
- scene revision；
- 正式计算 stale；
- 三套坐标系；
- GLB fallback；
- 正式/预览分离。

这些不是 PySide 特性，而是正确的领域设计。

迁移时应原样继承“规则”，只替换实现技术。

---

# 30. 最终架构完成后的数据流

## Teaching

```text
用户拖动 Lens
      │
      ↓
TransformControls
      │
      ↓
renderToTeaching()
      │
      ↓
TeachingStore.updatePose()
      │
      ├── revision + 1
      ├── mark formal result stale
      ├── update Inspector
      └── update Three Scene

用户点击「开始计算」
      │
      ↓
serialize scene snapshot
      │
      ↓
POST /api/v1/teaching/jobs
      │
      ↓
teaching_runtime
      │
      ↓
optical_core
      │
      ↓
Job result
      │
      ↓
WebSocket / REST
      │
      ↓
TeachingStore formalResults
      │
      ├── RayLayer
      ├── Analysis Panel
      └── Result Panel
```

## Simulation

```text
Project Store
   ↓
Request Compiler
   ↓
/api/v1/simulation/jobs
   ↓
Job Manager
   ↓
optical_runtime
   ↓
Result
   ↓
Result Store
   ↓
Charts / Views
```

---

# 31. 建议的最终决策

本项目不建议继续把新的复杂 3D 能力堆在 PySide + QML 上，同时也不建议现在把整个 Python 工程重写。

最合理路径是：

```text
Python Core           保留
FastAPI               保留并扩展
Machine Learning      保留
Teaching Runtime      保留
GLB Assets            保留

PySide UI             逐步退出
Qt Quick 3D           Three.js 替换
QML                    退出

Electron              新桌面壳
Vue + TS               新 UI
Pinia                  新前端状态
Three.js               新教学 3D
```

**第一优先级不是迁完 5 万行 UI，而是先证明 4 条核心链路：**

1. Electron 能稳定管理 Python 后端；
2. JS 能完整使用现有 Job / WebSocket；
3. Three.js 能与当前 Teaching 三套坐标完全一致；
4. Teaching 正式计算能通过 API 返回与旧版一致的结果。

这四条通过后，剩余工作基本属于可预测的 UI 迁移，而不是架构赌博。

---

# 32. 建议第一个 Sprint

## Sprint 1 目标

**产出一个可运行的 Electron migration prototype。**

### Day 1

- 创建 Vite + Vue + TS；
- 创建 Electron；
- FastAPI health。

### Day 2

- Backend Manager；
- API Client；
- WebSocket。

### Day 3

- Three Renderer；
- Breadboard；
- Camera；
- laser.glb。

### Day 4

- Teaching coordinates；
- lens/fiber；
- golden tests。

### Day 5

- Raycaster；
- TransformControls；
- SceneStore；
- revision。

### Sprint Exit

可以现场演示：

```text
启动 Electron
→ 自动连接 Python backend
→ 打开 Teaching Three.js
→ 看到实验台
→ 添加激光/透镜/光纤
→ 选中透镜
→ 移动透镜
→ Inspector 数值变化
→ revision 变化
→ 点击测试按钮调用 Python API
```

如果这个 Sprint 成功，即可正式进入全面迁移。

---

# 33. 最终验收标准

迁移完成版本必须满足：

### 架构

- [ ] JS Renderer 与 Python Core 零直接语言级耦合；
- [ ] 所有正式计算通过 FastAPI；
- [ ] 长任务统一 Job；
- [ ] Electron Main 只做桌面能力，不做业务计算。

### Teaching

- [ ] Three.js 完全取代 Qt Quick 3D；
- [ ] 当前 GLB 全部可加载；
- [ ] 三坐标 Golden Tests 通过；
- [ ] Scene Revision 一致；
- [ ] formal result stale 一致；
- [ ] 正式光学结果一致。

### 平台功能

- [ ] Simulation 主链路可用；
- [ ] Data 可用；
- [ ] Training 可用；
- [ ] Models 可用；
- [ ] Optimization 可用；
- [ ] Explainability 可用；
- [ ] Jobs 可用。

### 工程

- [ ] Unit tests 通过；
- [ ] Python tests 通过；
- [ ] E2E 通过；
- [ ] Windows clean-machine 安装运行通过；
- [ ] 日志完整；
- [ ] crash 可诊断；
- [ ] 无残留 Python backend process。

---

# 34. 最后建议

将这次工作定义为：

> **“Frontend Platform Migration”**

而不是：

> “把 PySide 代码翻译成 JS”。

前者会得到一个明确的前后端边界和可长期维护的 Three.js 教学平台；后者容易把 Qt 的结构、Signal、Widget 状态和历史包袱原样复制进 Web 技术栈。

迁移过程中最重要的两条原则：

> **业务语义复用，UI 实现重写。**

> **Python 负责算对，JS 负责展示、交互和编排。**

