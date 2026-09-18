## 2026-09-19

- Continued verification of the SHAP explainability-page redesign from the previous work session.
- Python syntax and `compileall` checks pass. Qt UI collection remains blocked by the machine's existing PySide6 `QtWidgets` DLL error `0xc0000139`; the backend SHAP contract check is also blocked by the environment's NumPy/SciPy mismatch (`numpy` has no `long`).

## [当前] - 将解释模块拆成三个独立二级页面

- **文件**: `frontend_pyside/modules/explainability/documents.py`, `frontend_pyside/modules/explainability/global_contrib.py`, `frontend_pyside/modules/explainability/param_trend.py`, `frontend_pyside/modules/explainability/current_system.py`, `frontend_pyside/app/workbench_shell.py`, `frontend_pyside/modules/home/shell.py`, `tests/test_teaching_v2_ui.py`, `tests/test_workbench_frozen_layout.py`
- **决策**: 将现有三个页面重新定义为“贡献排序 / 物理链路 / 当前系统验证”；贡献排序只展示 SHAP 排名，物理链路独立选择排名参数并展示箭头公式，当前系统验证保留局部瀑布图和验证摘要。
- **验证**: Python 语法编译和 `git diff --check` 通过；Qt UI 定向测试仍受本机 PySide6 `QtWidgets` DLL 错误 `0xc0000139` 阻塞。

## [当前] - 物理链路页增加图表/链路互斥切换

- **文件**: `frontend_pyside/modules/explainability/documents.py`, `frontend_pyside/resources/qss/light.qss`, `tests/test_teaching_v2_ui.py`
- **决策**: 在物理链路页首行加入“单参数贡献图 / 物理链路”两个互斥按钮；默认只显示单参数图，切换到物理链路后才显示参数选择与公式链路，错误状态自动回到可见的图表结果区。
- **验证**: Python 语法编译和 `git diff --check` 通过；Qt UI 定向测试仍受本机 PySide6 `QtWidgets` DLL 错误 `0xc0000139` 阻塞。

## [当前] - 物理链路中的公式改用数学富文本渲染

- **文件**: `frontend_pyside/modules/explainability/documents.py`, `tests/test_teaching_v2_ui.py`
- **决策**: 链路行不再使用紧凑纯文本公式，改为复用统一的 `formula_html` 与 `formula_latex` 展示上下标、分式和矩阵；没有公式映射时保留定位提示。
- **验证**: Python 语法编译和 `git diff --check` 通过；Qt UI 定向测试仍受本机 PySide6 `QtWidgets` DLL 错误 `0xc0000139` 阻塞。

## [当前] - 清理解释页空白和辅助说明

- **文件**: `frontend_pyside/modules/explainability/documents.py`
- **决策**: 移除“本页只负责回答”和“勾选 1–3 个参数”等辅助文字；无选中参数时不创建占位说明行；单参数图工作区改为紧凑固定高度且无结果时隐藏，避免隐藏/空结果控件撑出大块空白。
- **验证**: Python 语法编译和 `git diff --check` 通过；Qt UI 定向测试仍受本机 PySide6 `QtWidgets` DLL 错误 `0xc0000139` 阻塞。

## [当前] - 恢复解释图全高布局

- **文件**: `frontend_pyside/modules/explainability/documents.py`
- **决策**: 撤销固定高度和无结果隐藏策略，物理链路页恢复为顶部按钮行、下方图表占满剩余空间；仅移除多余辅助文字和链路空占位行。
- **验证**: Python 语法编译和 `git diff --check` 通过。

## [当前] - 收紧物理链路卡片并统一顶部按钮高度

- **文件**: `frontend_pyside/modules/explainability/documents.py`, `frontend_pyside/resources/qss/light.qss`
- **决策**: 参数选择卡和物理链路卡改为按内容高度布局，避免垂直扩展制造大块空白；“计算解释 / 单参数贡献图 / 物理链路”统一为 34px 高。
- **验证**: Python 语法编译和 `git diff --check` 通过。

## [当前] - 将物理链路改为去重的公式节点链

- **文件**: `frontend_pyside/modules/explainability/documents.py`, `frontend_pyside/resources/qss/light.qss`, `tests/test_teaching_v2_ui.py`
- **决策**: 不再为每个参数重复渲染同一条公式；按选中参数顺序去重公式节点，并追加一次复场重叠公式，显示“参数输入 → 中间公式 → 复场重叠 → 目标输出”，节点之间用箭头连接。
- **验证**: Python 语法编译、公式链静态断言和 `git diff --check` 通过。
