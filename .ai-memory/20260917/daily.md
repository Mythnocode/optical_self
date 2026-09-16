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
