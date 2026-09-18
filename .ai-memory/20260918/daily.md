## 2026-09-18

- Completed the generated arbitrary-lens sequence-data path: a dataset request can now request `sequence_long`; after the normal formal simulation and quality gate, valid samples are exported as `sequence_samples.csv` with one row per physical lens.
- The sequence export keeps a stable per-element feature schema (front/back geometry, aperture, air gap and receiver offsets), stores the path and column contract in manifest metadata, and the desktop reuses that contract to submit BiLSTM training directly from a selected generated dataset.
- Replaced the incorrect minimum/maximum lens count controls with an actual current-system physical-lens count. The variable selector controls simulation perturbations; the dataset continues to use the current system's real sequence length.
- Added `tests/test_sequence_dataset_export.py`; it passes with `PYTHONNOUSERSITE=1`. Qt UI tests remain blocked locally by the existing PySide6 QtWidgets DLL error `0xc0000139`.
- Fixed the BiLSTM training-result contract: point-level test `actual`, `predicted`, `residual`, and `sample_ids` are now returned by training, persisted in the model manifest, and exposed by the structure-model service so the existing residual/measured-vs-predicted charts can render.
- Fixed BiLSTM current-system prediction routing: sequence models now use `/structure-models/{model_id}/predict` with element types and per-element numeric values built from the current optical system; tabular models retain the legacy fixed-feature endpoint.
- Integrated the training-result plots described in `others`: test residuals now use actual simulation values on the x-axis and the built-in diagnostic plot, measured-vs-predicted uses the validation scatter with y=x and metrics, a residual histogram was added, and learning curves can show the test RMSE reference line.
- Added the SHAP sample-distribution/beeswarm chart to the global-contribution page using the existing cached point-level SHAP response; no hard-coded dataset/API loop from `others` is used.
- Returned BiLSTM training history and labeled its curve as standardized validation MSE so the training-result page can render its learning curve; static contract tests pass, while Qt UI tests remain blocked by the local PySide6 `QtWidgets` DLL error `0xc0000139`.
- Standardized trained-model display names to `{model type}{sequence number}` (for example `随机森林1`, `XGBoost物理残差1`, `BiLSTM1`) while keeping the internal model ID unchanged; legacy registry titles are normalized and their model numbers are persisted.
- Reused the dataset rail's custom card row for trained-model items in the model train-result/predict rails (and model-backed explainability rails), including the same selected check indicator; model selection is tracked separately from the internal model ID.
- Selecting a model now updates the rail check state and registry current-model state; a newly completed model is marked selected when its result rail is shown.
- Fixed external tabular dataset compatibility: imported files now normalize legacy `surface.N.*`/`wavelength_nm` feature names, infer and persist `design_variable_paths` plus physics-residual paths, and old imported manifests are backfilled during joint-training preflight. Legacy `active` surface features are reconstructed for prediction. Added `tests/test_external_dataset_import_contract.py`; the project `ml_datas/samples_flat.csv` now passes the joint-training preflight after import.
- Fixed dataset-page alignment by constraining the generation option grid to compact label columns and expanding editor columns; moved the training mode toggle beside “更多参数” and “开始训练” in the right-aligned action row.
- Simplified user-facing joint-training wording to “训练” in job titles, tooltips, completion summaries, and preflight errors; internal `joint_train` task/API names remain unchanged.
- Fixed historical training-result switching: selecting a model in the left rail now loads that model record into the result document before redrawing; newly completed model records also retain evaluation, training-history, OOB curve, and curve-label data needed by the charts.
- Removed middle-dot separators from the training-result summary and chart descriptions; metric/status parts now use normal spaces while unrelated SHAP and scan labels keep their existing wording.
- Renamed training-result chart options for clarity: “学习曲线” → “验证误差曲线”, and “实测对照” → “实测值与预测值对照”; updated chart routing, empty-state text, subtitles, and frozen UI expectations.

## [23:13] - Bug 修复: 对齐优化目标行中的当前值卡片与 RMS 复选框高度

- **文件**: `frontend_pyside/modules/optimization/documents.py`, `tests/test_workbench_frozen_layout.py`
- **决策**: 根据两个控件的自然高度取最大值，并将两者固定为同一高度，适配当前字体与 DPI；新增冻结布局回归断言。
- **验证**: Python 语法编译、`git diff --check` 和静态契约检查通过；Qt 测试仍受本机 PySide6 DLL 错误 `0xc0000139` 阻塞。

## [23:25] - 功能实现: 将优化页更多参数移入左栏双视图

- **文件**: `frontend_pyside/app/workbench_shell.py`, `frontend_pyside/modules/optimization/documents.py`, `frontend_pyside/modules/optimization/goal.py`, `frontend_pyside/modules/optimization/variables.py`, `frontend_pyside/resources/qss/light.qss`, `tests/test_workbench_frozen_layout.py`
- **决策**: 左栏新增“优化变量 / 更多参数”横向切换；目标检查器和最大评价次数由左栏持有，优化文档复用同一控件实例，主页面移除重复展开区。
- **验证**: 5 个 Python 文件语法编译通过，`git diff --check` 和静态交互契约检查通过；Qt 测试收集仍受本机 PySide6 DLL 错误 `0xc0000139` 阻塞。

## [23:34] - Bug 修复：准直约束展开后左栏内容被遮挡

- **文件**: `frontend_pyside/app/workbench_shell.py`, `tests/test_workbench_frozen_layout.py`
- **决策**: 明确“更多参数”滚动区域的竖向滚动策略和可伸缩尺寸；准直约束启用后，等待布局更新并自动将新增的末项滚入左栏可视区，避免展开内容溢出遮挡。
- **验证**: Python 语法编译和 `git diff --check` 通过；Qt UI 测试仍受本机 PySide6 QtCore DLL 错误 `0xc0000139` 阻塞。

## [23:40] - 回退：恢复准直约束原单列布局

- **决策**: 撤回上一轮新增的紧凑双列视觉布局；保留 `_labeled_field` 显式导入，避免优化模块启动时再次出现 `NameError`。

## [当前] - 重整 SHAP 解释页的阅读流程

- **文件**: `frontend_pyside/modules/explainability/documents.py`, `frontend_pyside/modules/shared.py`, `frontend_pyside/resources/qss/light.qss`, `tests/test_teaching_v2_ui.py`
- **决策**: 将全局 SHAP 页改为“贡献排序 → 勾选 1–3 个关键参数 → 物理链路 → 摘要按钮”的流程；模型分析、物理联系、下一步改成互斥的按钮式摘要，保留现有公式目录和“SHAP 不等于物理因果”的边界说明。
- **验证**: Python 语法编译、`compileall` 和 `git diff --check` 通过；针对性 Qt 测试仍受本机 PySide6 `QtWidgets` DLL 错误 `0xc0000139` 阻塞。
