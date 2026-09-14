# Teaching Center V2

教学画布、场景和物理适配仍在本包。产品入口是主窗口的 ``TeachingShell``，
不再通过整页 factory 挂载。

旧包 `frontend_pyside.features.teaching` 和整页 `TeachingV2Page` 已删除。

## 已实现的重构原则

- `SceneStore` 是唯一场景状态源；姿态内部统一为 `rad`，界面只在输入/显示边界换算为度。
- 每次编辑都会递增 `scene.revision`，旧的正式结果立即标记为过期。
- 教学世界原点是实验台基准，不是激光器。坐标分三套，互不混用：
  - `teaching_bench_mm`：`x` 导轨、`y` 横向、`z` 台面以上高度。默认梁高 25 mm 是台的属性。
  - `simulation_engine_mm`：\((X_e,Y_e,Z_e)=(Y_t,Z_t-\mathrm{axis\_height},X_t)\)，仅用于引擎和发布 `engine_nodes`。
  - `view3d_render`：\((X_r,Y_r,Z_r)=(X_t,Z_t,-Y_t)\)，Qt Y-up 实验台，**不是**引擎置换。渲染坐标不得写回 `Pose`。
- 「发布到仿真」快照带 `nodes`（教学）、`engine_nodes`（仿真）和 `frames` 标签，不自动修改仿真工作区。
- 几何预览在拖动和改参数后实时刷新，且不含假耦合效率。
- 波动/正式追迹只由「开始正式计算」触发；结果按 `geometry / raytrace / spot / field / coupling / wavefront` 分槽。
- 正式引擎不可用或接口失败时显示明确错误；不会把 Mock 结果伪装成正式结果。
- 教学工具栏提供独立的「成像」和「耦合」入口；点击后打开可移动的正式分析窗，分别显示光斑/像面指标和模式重叠/总耦合指标。
- 分析窗显示计算状态、耗时、警告和结果来源；场景版本变化后旧指标标记为过期，不能继续冒充当前场景结果。
- 「结果」窗口汇总当前场景的光路、成像和耦合状态；未计算、失败和过期结果均明确显示，不用空白区域代替状态。

## 文件说明

| 文件 | 作用 |
| --- | --- |
| `model.py` | 场景、器件、版本、结果状态和 JSON 持久化 |
| `coordinates.py` | 教学/引擎/渲染坐标显式转换 |
| `physics.py` | 几何预览与 `teaching_runtime` 正式引擎适配边界 |
| `tasks.py` | 手动正式计算、后台线程、过期结果保护 |
| `canvas.py` | 画布、器件拖动、基准线和光路显示 |
| `inspector.py` | 当前对象参数编辑（选择变化才重建） |
| `gizmo.py` | 轴/平面拾取，结果锁回教学 x/y/z |
| `view3d.py` / `qml/bench_view3d.qml` | 实验台 3D：程序几何占位、支柱、光线、gizmo、俯视正投影 |
| `assets.py` | 换皮：glb AABB 拟合到 Thorlabs 常用外壳；缺则回退 |
| `FIELD_MAP.md` | 字段已接 / 缺省 / 未接对照 |

## 冻结：字段 → 算对 → 画面跟手

已完成：工业常用值进场景与检查器；光学编译（含 ccd 别名与孔径优先）；程序侧光线/口径/支柱；朝向与镜子 45° 约定；正式追迹 opt-in 吃教学 SO(3)；缺 glb 回退程序几何；glb 按目录外壳缩放（激光不再用网格原尺寸）。

`teaching_runtime` 激光原点、现网入口切换仍未做。
