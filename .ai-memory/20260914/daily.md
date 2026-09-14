session-id: 20260914-2243
# 工作日志 - 2026-09-14

## [22:43] - 功能实现: 更新首页工作流布局并完成视觉验证

- **文件**: `frontend_pyside/app/workbench_shell.py`, `frontend_pyside/resources/qss/light.qss`
- **决策**: 使用原生 Qt 工作流卡片、图标和连接线替换旧网格；保留 `WorkflowHome` 信号和 `MainWindow` 路由；字体族继承应用全局字体，仅调整字号和字重。
- **验证**: Python 编译通过；8 个首页节点路由和 `quick_start` 信号通过；实际主窗口首页入口点击通过；1280×800 与 1024 宽度截图通过视觉检查；相关布局测试通过。

## [23:05] - 视觉修正: 连接箭头和仿真标题

- **文件**: `frontend_pyside/app/workbench_shell.py`, `frontend_pyside/resources/qss/light.qss`
- **决策**: 用 `WorkflowConnector` 自绘完整上下/左右箭头，避免固定字体字形裁切；将仿真标题改为固定 220×52 的左上角紧凑标签，并限制仿真面板垂直伸缩。
- **验证**: 2502×1381 与 1280×800 离屏截图通过视觉检查；8 个节点路由、主导航首页返回、快速开始和字体族一致性通过；`test_workbench_frozen_layout.py` 通过。

## [23:15] - 视觉微调: 放大首页按钮文字

- **文件**: `frontend_pyside/resources/qss/light.qss`
- **决策**: 保持原字体族不变，将工作流卡片标题从 13pt 调至 17pt、副标题从 10.5pt 调至 13pt，仿真标签标题调至 15pt。
- **验证**: 1280×800 与 1024×800 截图未出现文字溢出、箭头挤压或卡片重叠。
