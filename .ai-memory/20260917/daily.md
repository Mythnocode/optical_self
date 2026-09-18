## [当前] - 绘图结构简化: 端面匹配图独立化

- **文件**：`frontend_pyside/shared/plotting/beam_match.py`、`canvas_parts/canvas_2d.py`、`result_workspace.py`、`fast_heatmap.py`。
- **决策**：将截图中的端面匹配图统一收拢到 `plot_beam_match()`；结果工作区不再把 `beam_match` 送入快速热图，页面显示和 Matplotlib 导出共用同一函数；移除快速热图中的重复端面匹配绘制代码。
- **验证**：相关目录 compileall 通过；Matplotlib 合成数据 smoke test 通过；绘图入口静态检查通过；`git diff --check` 通过。

## [当前] - Bug 修复: 端面匹配图布局恢复

- **原因**：Matplotlib 版剖面使用完整坐标轴，而热图使用裁剪坐标，导致主热图缩小；独立函数中的侧剖面位置也与原 Qt 布局不一致。
- **修复**：剖面改用 `x_view/y_view` 和对应切片；侧剖面恢复到左侧；移除原截图没有的颜色条和右侧重复指标框；主图页面与导出继续共用 `plot_beam_match()`。
- **验证**：compileall 通过；合成数据 smoke test 的主坐标范围和侧剖面位置符合预期。

## [当前] - Bug 修复: 边缘曲线与主热图像素对齐

- **原因**：`set_aspect("equal", adjustable="box")` 在非正方形窗口中按数据范围缩小主轴，导致上方曲线宽度与热图不同、左侧曲线高度与热图不同。
- **修复**：在 `beam_match.py` 中按 Figure 宽高计算正方形主轴尺寸；上方/左侧坐标轴复用主轴的宽度/高度；取消共享轴导致的布局干扰，手动同步裁剪后的坐标范围。
- **验证**：compileall 通过；合成数据 smoke test 验证三轴宽高对齐且主图像素尺寸为正方形。

## [当前] - 回退: 恢复端面匹配原绘图路径

- **原因**：用户希望保留原来的 Qt/QImage 端面匹配图，不采用独立 `beam_match.py` 的 Matplotlib 方案。
- **修复**：恢复 `ResultWorkspace` 对 `beam_match` 的快速热图分流；恢复 `fast_heatmap.py` 的 `_profile_path`、`_draw_beam_match` 和 `paintEvent` 分支；恢复 `canvas_2d.py` 的 Matplotlib 备用 `_beam_match`；删除独立绘图文件。
- **验证**：相关目录 compileall 通过；独立函数入口不存在；`git diff --check` 通过。

## [当前] - Bug 定位: Windows 状态文件替换失败

- **症状**：`FileJobRepository.save_status()` 在 `atomic_files.atomic_write_bytes()` 的 `os.replace(tmp, target)` 抛出 `PermissionError: [WinError 5]`。
- **定位**：任务目录存在且 `status.json` 可读；当前只发现一个 Optical 后端进程；用临时文件复现了 Windows 下目标文件仍被读取句柄占用时 `os.replace` 会失败。`atomic_write_bytes` 当前没有重试，因此瞬时文件锁会直接冒泡到 persistent worker 消息处理。
- **影响**：该任务状态文件仍为 `running / 0.94 / optical_engine.finalizing / result_available=false`，结果交接可能被中断；本轮只诊断未改代码。

## [22:13] - 机器学习模块同步: 迁移 theML 算法版本

- **文件**：`machine_learning/training/service.py`、`backend/optical_ml_app/application/model_extension_service.py`、`tests/test_shap_request_validation.py`。
- **决策**：随机森林与 XGBoost 统一使用完整特征向量；SHAP 默认展示完整模型特征；同步更新旧的 SHAP 函数签名与默认行为测试。`models`、`optimization`、SHAP 核心算法与 BiLSTM 已确认和 theML 一致，无需复制。
- **验证**：两处目标源码与 theML 内容一致（忽略换行差异）；相关源码编译通过；SHAP/混合优化测试 `6 passed`；确认工作区外无 `theML` 引用后删除 `D:\AAAWorkspace\optical_self\theML`。

## [22:28] - 功能实现: 统一数据集显示名称

- **文件**：`frontend_pyside/app/workbench_shell.py`、`tests/test_dataset_display_naming.py`。
- **决策**：生成数据集使用“数据集1、数据集2……”的会话内递增名称，导入数据集沿用文件名；后端真实 `dataset_id` 保持不变，并将生成名称同步到生成请求和当前数据集记录。
- **验证**：目标源码与测试文件 `py_compile` 通过；`git diff --check` 通过；Qt 测试因当前环境 PySide6 `QtWidgets` DLL 加载失败未能执行。

## [22:34] - 重构: 删除 SurfaceTypeSpec.description

- **文件**：`frontend_pyside/features/simulation/surface_registry.py`、`frontend_pyside/features/simulation/components/editor_parts/property_behavior.py`。
- **决策**：移除 `SurfaceTypeSpec.description` 字段及各表面类型的说明文本，同时删除属性编辑器中的类型说明标签；动态参数从第 0 行开始，保留类型参数和空状态提示。
- **验证**：目标源码编译通过；6 个表面/镜片相关测试通过；已确认项目内不存在对 `SurfaceTypeSpec.description` 的剩余引用。冻结布局测试另有 1 项因已有导航项顺序断言失败，与本次改动无关。

## [22:58] - 功能实现: 重构模型页数据集选择流程

- **文件**：`frontend_pyside/modules/model/documents.py`、`frontend_pyside/app/workbench_shell.py`、`tests/test_dataset_source_flow.py`。
- **决策**：数据集页改为 `1. 数据` / `2. 训练`；数据来源先选“导入/生成”，导入模式提供“按照镜头/按照元件”、显式“选择文件→导入”以及相邻的“内置”按钮；生成模式默认只显示样本数和目标变量，其他参数通过右侧箭头展开。文件、内置、生成结果使用显式活动数据源，训练不再仅凭隐藏下拉框误选数据集。
- **验证**：目标源码和回归测试编译通过；9 个相关测试通过；Qt offscreen 冒烟与三种页面状态截图检查通过；`git diff --check` 通过。

## [22:58] - 状态完善: 切换数据来源时清理旧数据集

- **文件**：`frontend_pyside/modules/model/documents.py`、`tests/test_dataset_source_flow.py`。
- **决策**：从“内置/导入”切到“生成”或从“生成”切回“导入”时清空旧的活动数据集 ID，避免跨模式误训练。
- **验证**：相关源码编译通过；数据来源流程测试及相关回归测试共 9 项通过。

## [22:59] - 测试同步: 更新数据集页面冻结断言

- **文件**：`tests/test_workbench_frozen_layout.py`。
- **决策**：将冻结测试中的数据集页面期望同步为两段式数据/训练布局、导入/生成模式和显式导入按钮；保留其余训练与预测覆盖。
- **验证**：文件编译通过；该测试仍在前置的仿真二级导航顺序断言处失败（`materials` 与 `layout` 顺序/条目差异），未进入数据集断言。

## [23:16] - 功能实现: 左侧数据集选择与生成任务进度

- **文件**：`frontend_pyside/modules/model/documents.py`、`frontend_pyside/app/workbench_shell.py`、`frontend_pyside/resources/qss/light.qss`、`tests/test_workbench_frozen_layout.py`、`tests/test_dataset_rail_state.py`。
- **决策**：删除数据页旧的全宽状态表；左侧数据集条目改为可显示右侧绿色选中图标和生成进度条。提交生成任务时先插入临时“数据集生成”条目，任务进度只更新该条目，后端完成后原地改名为顺序命名的“数据集N”；训练沿用左侧当前选中的数据集 ID，生成失败时移除临时条目。
- **验证**：源码编译通过；数据集来源、命名和左侧任务生命周期测试通过；Qt offscreen 截图确认进度条和绿色对勾布局可见；`git diff --check` 通过。

## [23:21] - 兼容完善: 移除状态表后的错误提示

- **文件**：`frontend_pyside/app/workbench_shell.py`。
- **决策**：生成参数校验失败和文件导入失败改由任务提示通道反馈，避免删除旧状态表后错误信息无处显示。
- **验证**：相关 11 项测试、目标源码编译和 `git diff --check` 均通过。

## [2026-09-18] - 数据集任务: 取消总时限并保留失败记录

- **文件**：`backend/optical_ml_app/application/dataset_service.py`、`backend/optical_ml_app/jobs/task_manager.py`、`frontend_pyside/app/workbench_jobs.py`、`frontend_pyside/app/workbench_shell.py`、`frontend_pyside/resources/qss/light.qss`、`tests/test_dataset_runtime_budget.py`、`tests/test_dataset_rail_state.py`。
- **决策**：数据集生成不再设置总墙钟超时；保留连续 300 秒无进展的卡死保护，并在重试旧任务时移除历史总时限。左栏生成条目新增取消按钮；取消请求确认前显示“取消中”，最终保留灰叉“已取消”；失败任务保留红叉“生成失败”及错误提示，不可作为训练数据集。
- **定位依据**：`job-a9619e0d5f61` 在 `dataset.batch.evaluate` 已运行并达到 56% 后，于恰好 780 秒被 `TIMEOUT` 终止，证明是旧的样本数推导总时限而不是无进展。
- **验证**：目标源码 `py_compile` 通过，`git diff --check` 通过；新增状态测试覆盖失败保留、红叉、取消入口和取消中禁用。当前 `D:\anacondanew\python.exe` 的 PySide6 DLL 加载失败、SciPy/NumPy ABI 版本不兼容，导致 pytest 在收集阶段失败，未能执行 Qt 运行态测试。

## [2026-09-18] - 训练模式按钮: 双色同级状态

- **文件**：`frontend_pyside/modules/model/documents.py`、`frontend_pyside/resources/qss/light.qss`、`tests/test_dataset_source_flow.py`。
- **决策**：固定镜头数（随机森林 + XGBoost）采用橙色，任意镜头数（BiLSTM）采用绿色；开始训练仍为蓝色主操作。通过 `trainingMode` 动态属性和 QSS 专用选择器实现，切换时重新 polish 控件以保证样式即时刷新。
- **验证**：目标源码与更新的流程测试 `py_compile` 通过，`git diff --check` 通过；Qt 运行态测试仍受本机 PySide6 DLL 环境阻塞。

## [2026-09-18] - 训练区: 增加更多参数并右对齐主操作

- **文件**：`frontend_pyside/modules/model/documents.py`、`frontend_pyside/resources/qss/light.qss`、`tests/test_dataset_source_flow.py`。
- **决策**：训练区底部保持“固定镜头数/任意镜头数”在左侧，右侧同一行放置“更多参数”和“开始训练”；默认隐藏随机森林、XGBoost、BiLSTM 的具体参数，点击“更多参数”展开，再次点击收起；切换训练模式时自动收起参数区。
- **验证**：目标源码与流程测试 `py_compile` 通过，`git diff --check` 通过。

## [2026-09-18] - 数据集页: 任意镜头数与自定义变量方案界面

- **文件**：`frontend_pyside/modules/model/documents.py`、`frontend_pyside/resources/qss/light.qss`、`tests/test_dataset_source_flow.py`。
- **决策**：数据集生成区域新增同页的“固定镜头数 / 任意镜头数”切换，随训练数据结构同步；固定模式沿用预设镜头数和变量方案，任意模式显示最小/最大镜头数及本页可勾选的任意变量列表。序列数据生成后端尚未实现时，按钮明确显示“序列生成待接入”且禁用，避免误提交固定结构生成任务。
- **验证**：源码和测试编译通过，`git diff --check` 通过；流程测试覆盖模式、变量选择和禁用态，但当前解释器在导入 PySide6 QtWidgets 时 DLL 加载失败，pytest 在收集期停止，未能执行运行态断言。
