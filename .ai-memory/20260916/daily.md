session-id: 20260916-1200

## 功能删除：移除无限画布模块并保留现有前端入口

- **范围**：删除 `frontend_pyside/features/canvas/*` 无限 QGraphics 节点画布、其专属测试、画布验收脚本及生成验收产物。
- **迁移**：把普通工作台仍使用的参数目录、任务 payload/错误提示和 SHAP 错误提示分别迁移到 `frontend_pyside/app`、`features/simulation` 与 `features/explainability`，避免普通仿真、训练、扫描、优化和解释页面出现悬空导入。
- **保留**：`frontend_pyside/shared/plotting/canvas.py` 科学绘图画布、`frontend_pyside/features/teaching_v2/canvas.py` 教学二维画布、教学三维视图及历史方案文档。
- **入口**：当前一级入口为首页、仿真、教学、模型、优化、解释；主窗口仍由 `app.py/run_frontend.py -> frontend_pyside.app.main -> bootstrap -> MainWindow` 启动。
- **验证**：画布包路径不存在且 `find_spec` 返回 `None`；全量运行时代码/测试/工具引用扫描无画布引用；相关回归测试 80 passed；主窗口离屏启动成功；知识图谱重建报告 dangling 0。

## [12:00] - 配置变更: Qt 界面统一使用单一字体

- **文件**：`frontend_pyside/shared/font_fallback.py`
- **决策**：Qt 界面字体固定为 `Microsoft YaHei UI`，不再按中英文分别选择字体；`main_window.py` 与 `main_window_layout.py` 不需要改动。
- **验证**：模块编译通过；`qt_font_families()` 和实际配置字体均只返回 `Microsoft YaHei UI`；界面回归测试 16 passed。

## [12:00] - 界面配置: 窗口标题只显示 APP_NAME

- **文件**：`frontend_pyside/app/main_window.py`
- **决策**：窗口标题的初始设置和刷新逻辑统一只使用 `APP_NAME`；项目名、版本号和后端连接状态仍保留在内部状态流程中，但不再拼接到标题栏。
- **验证**：模块编译通过；离屏主窗口初始标题和后端状态刷新后的标题均等于 `APP_NAME`；相关 UI 回归测试 16 passed。

## [12:30] - 重构: 按 Tab 拆分前端文档实现

- **文件**：`frontend_pyside/tabs/*`、`frontend_pyside/app/workbench_shell.py`
- **决策**：将镜头数据/示意图、设置、仿真结果、模型、优化和可解释性文档移到 Tab 归属模块；工作台只保留导航、对象栏、文档工作区和任务编排；共享元数据与无状态 UI 辅助放入 `tabs/shared.py`。
- **验证**：`compileall` 通过；Tab 所有权静态检查通过；依赖方向检查通过；`tests/test_dataset_split.py` 4 passed。Qt UI 测试受当前环境 `PySide6` DLL 加载失败影响，未能收集。
## [12:35] - 结构细化: 每个可见 Tab 增加独立入口文件

- **文件**：`frontend_pyside/tabs/model/*`、`frontend_pyside/tabs/optimization/*`、`frontend_pyside/tabs/explainability/*`、`frontend_pyside/tabs/simulation/materials.py`
- **决策**：各可见 Tab 使用轻量入口类固定 kind 和构造参数；共享的复杂布局实现保留在对应领域的 `documents.py`，避免重复状态逻辑。
- **验证**：全量 `frontend_pyside` 编译通过；Tab 源码编码/空白检查通过；`tests/test_dataset_split.py` 4 passed。
## [12:40] - 优化目标检查器继续拆分

- 将 `OptimizationGoalInspector` 移入 `frontend_pyside/tabs/optimization/goal.py`。
- `optimization/documents.py` 通过 Tab 包内模块复用检查器；`workbench_shell.py` 仅保留兼容性导入供对象栏使用。
- 完成 `compileall`、Tab 依赖方向检查和数据集拆分测试。
## [13:05] - 按一级入口重组前端模块

- 将原 `frontend_pyside/tabs` 归并为 `frontend_pyside/modules`，按 `home/simulation/teaching/model/optimization/explainability` 分域。
- 将 `WorkflowHome` 与 `TeachingShell` 及教学浮窗从 `workbench_shell.py` 移入对应入口包。
- `app` 仅保留顶层路由、布局和跨域编排；完成 compileall、源码检查和数据集测试。
## [13:25] - 页面元数据下沉到一级入口

- 为各可见页面增加 `PageSpec`，仿真页面拆分为镜头数据、材料库、光路图、光斑图、光纤耦合和波前与衍射入口文件。
- 新增 `modules/navigation.py` 作为轻量汇总层，`modules/shared.py` 不再承载一级/二级导航配置。
- `workbench_shell.py` 改为显式导入共享 helper，移除动态 `globals().update()`，消除未定义名称静态告警。
- 验证：compileall 通过、仿真页面归属检查通过、数据集测试 4 passed。

## [当前] - 文档化: 完善仿真页面模块注释

- **文件**：`frontend_pyside/modules/simulation/*.py`
- **决策**：为仿真一级入口下的 11 个 Python 文件补充模块、类、方法和关键流程注释，说明页面注册、镜头编辑、示意图、正式结果、结果版本和设置状态之间的职责边界；不修改业务逻辑。
- **验证**：`python -m compileall -q frontend_pyside/modules/simulation` 通过；AST 检查显示类和函数缺失文档字符串数量为 0。

## [当前] - Bug 修复: 补齐光纤耦合页面元数据

- **文件**：`frontend_pyside/modules/simulation/fiber_coupling.py`
- **决策**：为 `PageSpec` 补齐页面标题和副标题两个必填字段，保持菜单信息、工作台标题和 `coupling` 结果类型一致。
- **验证**：仿真页面的 `PageSpec` 参数检查 `15 calls; invalid=0`；`frontend_pyside/modules` compileall 通过。

## [当前] - 文档化: 完善绘图链路注释

- **文件**：`frontend_pyside/features/simulation/adapters/*`、`frontend_pyside/shared/plotting/*`。
- **决策**：补充仿真结果到绘图载荷、结果工作区分流、快速热图、Matplotlib 2D/3D、光学场景、交互、坐标变换、样式和缓存的模块/类/函数说明；不改变绘图算法和页面路由。
- **验证**：`frontend_pyside/shared/plotting` 与 `frontend_pyside/features/simulation/adapters` compileall 通过；核心绘图文件 AST 缺失类/函数文档数量为 0；`git diff --check` 通过。
