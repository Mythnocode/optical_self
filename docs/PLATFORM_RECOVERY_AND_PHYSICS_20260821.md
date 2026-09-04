# 虚拟光学平台恢复与物理可信度改进说明

日期：2026-08-21  
适用版本：`optical-ml-platform 1.5.6` 本交付源码

## 1. 本次完成内容

| 领域 | 已实现内容 | 结果约束 |
| --- | --- | --- |
| 器件搭建 | 3D 场景接收元件库 MIME 拖放；屏幕射线与光学平台平面求交后再换算场景坐标；搭建、观察、测量、分析均有明确入口 | 拖放只写入统一实验模型，不另建 3D 私有状态 |
| 光线可信度 | 2D/3D 红色光线只使用正式 `raytrace` 返回的光线；场景拓扑不再伪装成物理光路 | 等待、失败或过期时不显示红色物理光线 |
| 结果时效 | 场景修订号、任务代次和有限重试共同阻止旧结果覆盖新状态 | 正式结果必须与当前场景版本一致 |
| 几何可行性 | 正式计算前检查顺序、间隙/重叠、处方、口径、波段、接收器、NA、偏振和系统长度 | 阻断项出现时结果标为“不可用”，不输出伪效率 |
| 相机/接收面 | 相机必须同时满足正式光线到达与接收面角色；输出像元、背景、饱和、质心、椭圆率、RMSx、RMSy、径向 RMS 与 1/e² 半径 | 未命中时不生成成像预览，不沿用旧读数 |
| 结果来源 | 光线来源、效率来源、验证状态分别保存和显示 | “教学估算”“正式追迹”“实验数据”“代理模型”不再混称 |
| SHAP | 恢复顶栏一级“模型解释”；恢复“解释分析/解释报告”；提供明显的独立窗口按钮和物理核验区域 | SHAP 统一表述为“模型中的候选主导因素” |
| SHAP 可靠性 | 增加样本量、独立测试 R²、加和一致性、分布外和正式核验门槛 | 门槛不满足时降级提示，不把统计贡献写成物理原因 |
| 原理分析 | 恢复“分析→原理分析”；侧面板随当前实验状态刷新；显示可行性、正式光线、结果来源和接收面指标 | 观察、解释、数据来源、操作建议与适用边界分离 |
| 失配覆盖 | 横向、轴向、角度、尺寸、曲率、孔径、未命中、偏振、采样和复合失配均有入口 | 不强制把复合问题归为一个唯一原因 |
| 波段/透镜/耦合 | 材料与镀膜波段、口径、厚度、曲率、方向、NA、接收方式和偏振进入可行性检查 | 超适用范围时禁止显示为正式验证 |
| 四透镜实验 | 新增 LM135C 四透镜 780 nm 基准：光束椭圆参数、M²、焦距组合、间距、相机扫描位置、4.65 μm 像元及 M=1 | 未提供制造商曲率/材料资料时明确标注为焦距派生近似处方 |
| 架构清理 | 工作台改为类工厂注入；停止模块级猴子补丁；原理面板与 2D/3D 共用同一模型快照；正式物理独立适配 | 保留仍被调用的兼容模块，避免误删隐式依赖 |
| 界面适配 | 训练表单设置独立最小触控高度；底层工作台避免拖动期间销毁当前图元 | 覆盖紧凑桌面窗口和高 DPI 基本约束 |

## 2. LM135C 处方边界

当前附件和源码没有给出四片镜片的制造商逐面处方（每面曲率半径、中心厚度、材料、有效口径、圆锥常数、镀膜有效波段和安装方向）。本交付没有虚构这些数据：

- 有明确处方时，正式项目构建器直接使用逐面参数和安装方向；
- 只有焦距时，平台生成带 `approximate` 标记的焦距派生近似处方；
- 近似处方及未知镀膜会产生验证提示，不能冒充器件级实物核验；
- 要完成 LM135C 实物级验证，应把制造商或实测处方录入镜片参数后，再比较实验与正式仿真的 RMSx/RMSy、径向 RMS、质心、椭圆率和残差。

## 3. 运行方法

推荐 Python 3.11—3.13：

```bash
python -m venv .venv
.venv/bin/python -m pip install -r requirements/requirements.txt
```

先启动后端：

```bash
.venv/bin/python run_backend.py
```

再开一个终端启动桌面端：

```bash
.venv/bin/python run_frontend.py
```

Windows 对应命令把 `.venv/bin/python` 换成 `.venv\\Scripts\\python.exe`。中文图表建议安装“思源黑体/Noto Sans CJK SC”，否则程序仍可运行，但 Matplotlib 可能提示缺少中文字形。

## 4. 验证结果

本交付在 Linux 无头 Qt 环境完成以下验证：

```text
pytest: 153 passed
Python compileall: passed
QML teaching scene: Status.Ready
formal teaching raytrace adapter: success, 441 formal paths
```

回归测试包括拖拽入口、正式光线隔离、相机门控、场景版本、可行性、波段/处方、SHAP 可靠性、一级导航、原理分析、紧凑布局、后台进程和 LM135C 基准。

## 5. 主要源码位置

- `frontend_pyside/features/teaching/applicability.py`：器件、波段、处方和耦合可行性。
- `frontend_pyside/features/teaching/formal_physics.py`：正式计算前置检查、项目映射、版本和结果来源。
- `frontend_pyside/features/teaching/experiment_scene.py`：正式光线到统一 2D/3D 场景的投影。
- `frontend_pyside/features/teaching/unified_workbench.py`：唯一教学实验状态与测量定义。
- `frontend_pyside/features/teaching/exploration_panel.py`：随场景联动的原理分析。
- `frontend_pyside/features/explainability/`：SHAP 工作区、可靠性门槛、物理核验和报告。
- `teaching_runtime/physical_scene.py`：正式 `raytrace` 结果到教学场景的适配。
- `tests/test_platform_recovery_improvements.py`：本轮核心功能保全测试。

