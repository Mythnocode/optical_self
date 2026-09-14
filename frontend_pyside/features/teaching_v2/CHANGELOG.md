# V2 重构交接清单

## 新增文件

全部位于 `frontend_pyside/features/teaching_v2/`，与旧教学中心并列，互不导入。

## 未修改文件

旧教学中心 `frontend_pyside/features/teaching/`、画布教学节点、页面注册表和仿真页面均未修改。新旧版本可以同时安装。

`teaching_runtime/physical_scene.py` 仅增加 opt-in：`orientation_source=teaching_engine_so3` 时吃 `tilt_*` / `axis_engine`；激光原点与旧路径未改。

## 交付前注意

1. 运行 `python -m frontend_pyside.features.teaching_v2.smoke_test`（offscreen）。
2. 运行 `python -m pytest tests/test_teaching_v2_core.py tests/test_teaching_v2_ui.py -q`。
3. 运行 `python -m frontend_pyside.features.teaching_v2.assets`（只检查文件名与非空）。
4. 正式引擎若返回耦合效率字段，可在 `ResultCard` 显示；若未返回，界面会明确提示，不会填入教学估算值。
5. 通过坐标、拖动、结果版本、正式计算和发布快照验收后，再决定是否把预览入口接到产品导航。

## 字段 → 编译 → 程序几何（本轮）

- 对照表：`FIELD_MAP.md`。
- 激光 `beam_radius_mm=0.72`；透镜可选 R1/R2/CT；CCD 靶面宽×高；`ccd` 编译为 `imaging_camera`。
- 无光纤拒绝耦合/场/波前；光斑需要 CCD 或光纤。倾角：V2 正式追迹 opt-in 吃教学 SO(3)；旧教学路径仍相对激光。
- 实时视图：扁圆柱/圆盘 + `z_mm` 支柱 + 朝向；缺 glb 不阻塞。俯视用 3D 正投影。
- 3b：正式追迹 opt-in 吃教学 SO(3) `tilt_*`（不改激光原点）。
- 换皮管道：`assets/<key>.glb`（+X 光轴）拟合到 Thorlabs 常用外壳（激光 Ø11×40，透镜随外径，光纤 Ø11×18，CCD 30×30×21.8，镜子 Ø12.7×6，支柱 Ø12.7×`z_mm`）；无网格时占位圆柱仍 +Y 对准光轴。
- 引擎指标别名（Strehl / RMS / 耦合）；CCD 像距接到终端面（终端已是末面时 sequential `image_distance` 仅留 0.001 mm）；光纤接收偏移吃教学 y；检查器 R1/R2/孔径「未设」。


## 坐标冻结（自由 3D）

- `view3d_render` 从引擎置换拆开：`(X_r, Y_r, Z_r) = (X_t, Z_t, −Y_t)`。
- 发布快照增加 `frames` 标签。`Pose` 仍只存教学毫米。
- 3D 视口：轨道相机、教学轴/平面 gizmo、Ctrl+轴旋转、光线叠加。姿态用 ``P R Pᵀ`` 发布到仿真。
