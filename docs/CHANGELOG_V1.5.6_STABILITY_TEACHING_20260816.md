# v1.5.6 稳定性、按需结果与教学中心改进验收说明（2026-08-16）

本轮从 `optical_ml_workspace_v1.5.6_lazy_results_guidance_verified_20260816.zip` 继续开发，没有回退到旧版，也没有修改 `optical_core` 物理/数值内核。

## 1. 仿真结果真正按需计算

- 完整结果目录始终可见，未计算结果不再从导航中消失。
- 默认正式仿真改为只计算当前可见结果（默认光路/raytrace），不再首次就预算 `psf`、`coupling` 等隐藏分析。
- 点击 PSF 才补算 `psf`，并共享解锁 PSF、焦面截面、光斑尺寸、MTF。
- 点击相位才补算 `coupling`，并共享解锁振幅、相位、端面匹配、光纤基模等派生视图。
- 能量分解仍严格等待 `power_audit`，不会因 coupling 已完成而错误标成可用。
- 已缓存视图重复打开不会创建新 job。

真实 GUI/后端证据：`assets_3d/reports/v156_real_workflows_final/`。

## 2. AI Guidance 连续引导与安全边界

- AI 的主建议只“准备/定位”，不会直接启动正式耗时计算。
- 用户真实点击确认后，Guidance Session 跟踪真实后端 job。
- job 完成后自动继续到下一阶段建议，不再在一个 Action 后断链。
- 修复极快任务在 WebSocket 订阅建立前完成时可能漏掉终态的问题：中央 Job Monitor 使用 WebSocket 实时推送 + 低频 HTTP 真值对账。
- 旧 HTTP 进度不能覆盖更新的 WebSocket 进度；运行态永不显示 100%，100% 只属于 confirmed completed。

## 3. 任务稳定性与进度一致性

真实任务中心已验证：

- 一个任务 running、另一个 queued；
- 同一任务多次真实进度更新；
- 运行中取消；
- cancelled 后 Retry 创建新的真实 job id；
- completed 后 `result_available=true` 并能下载真实结果；
- failed job 不暴露伪结果；
- Retry 按钮服从后端 `error.retryable`。

证据：`assets_3d/reports/task_lifecycle_cachefix/`。

## 4. 501 点扫描内存稳定性

发现并修复两个根因：

1. `run_backend.py` 原先模块级导入 FastAPI app，multiprocessing `spawn` 的 worker 会重建服务图并误运行“后端重启恢复”。现改为只在真实 parent `main()` 内导入 app。
2. 长扫描曾保留大量 dense `SimulationResult` / PreparedCoupling 缓存，worker 可增长到约 2.2 GiB 并 `WORKER_EXITED`。现改为：
   - 扫描小批次计算并立即降维提取 scalar metrics；
   - 每批次释放 dense result；
   - 每批次清理 PreparedCoupling 的瞬态 mode/evaluation 缓存，但保留共享 ray-trace cache；
   - 不修改任何物理公式、光线追迹或波动传播算法。

真实 501/501 扫描复验：

- terminal = completed
- result_available = true
- worker compute ≈ 13.7 s
- 后端子进程峰值 RSS ≈ 428.7 MiB
- 未再出现 `WORKER_EXITED`

证据：`assets_3d/reports/scan_memory_cachefix/`。

## 5. 教学中心大画布改进

- 不增加“搭建→预测→操作→测量→规律→解释”常驻步骤条。
- 默认保持大实验画布；器材、当前对象、测量/原理均按需展开/覆盖，而非永久三栏切割画布。
- 缩窄左右 Drawer/Inspector，压缩底部重复状态区。
- 1366×768 与 1920×1080 均已截图检查。

证据：`assets_3d/reports/teaching_layout_final/`。

## 6. 教学 3D 基本机械真实性

教学模型不追求 CAD 级还原，但核心器件必须满足“光学件 + 基本机械支撑 + 台面接触”：

- 透镜/光阑/反射镜等保留镜架、支柱、底座；
- 激光器补充双支柱与底座；
- 隔离器补充支撑和底座；
- 光纤调整台强化夹持/调整台/底座表达；
- 各器件统一到台面接触高度，避免悬浮。

真实 OpenGL Quick3D 已验证 pick、drag、orbit、pan、zoom、多视角截图、draw-call/vertex 预算与内存切换。

证据：`assets_3d/reports/full_workbench_final/`、`assets_3d/reports/interaction_final/`。

> 当前容器使用 Xvfb + Mesa llvmpipe 软件 OpenGL。它可以证明真实 QRhi/OpenGL 渲染与交互正确性，但不能替代目标 Windows GPU 的 FPS/VRAM 性能验收。

## 7. 机器学习真实训练

真实 GUI 点击“开始训练”后：

- 后端训练 job completed；
- UI 进度 100%；
- 新模型进入 recent model；
- 不自动替换 current model；
- “设为当前模型”必须由用户显式操作。

证据：`assets_3d/reports/ml_training_real_cachefix/`。

## 8. 八类用户验收

八类用户均有 QTest 真实 UI 点击回归；涉及耗时科研动作的角色另外绑定真实后端终态证据：

1. AI 引导型新手
2. 自主探索型新手
3. 光学科研用户
4. 实验验证用户
5. 机器学习研究用户
6. 教师/学生用户
7. 故障恢复用户
8. 熟练高频用户

汇总：`assets_3d/reports/eight_users_final_report.json`，截图：`assets_3d/reports/eight_users_final/`。

## 9. 物理内核冻结

当前工作树 `optical_core` 与用户上传的 v1.5.6 基线 ZIP 逐文件 SHA256 比较：

- baseline files: 418
- modified: 0
- missing: 0
- extra: 0
- status: PASS

证据：`assets_3d/reports/optical_core_frozen_report.json`。

## 10. 自动测试

项目现有 8 个测试文件共收集 46 个测试，断言全部通过；另有真实 GUI、真实后端、Quick3D 和 501 点长扫描专项门禁。最终交付包还必须从 ZIP 解压到新目录再复验关键门禁后才可标记 verified。
