# 功能守恒验收

界面允许重排/分级，但正式能力不能因简化而消失。

| 功能域 | 守恒要求 | 状态 | 说明 |
|---|---|---|---|
| 全平台能力目录 | 所有正式能力仍可从工具箱两层以内发现 | **FAIL** | 缺少：研究与优化、实验验证 |
| 专业光学分析 | 6组分析器及全部既有结果视图保留 | **PASS** | — |
| 光纤/接收端 | 接收类型与模式模型未因侧栏压缩而删除 | **PASS** | — |
| 光学表面/镜头编辑 | Surface 类型与非球面高级参数保留 | **PASS** | — |
| 研究/优化/两类反向 | 参数研究、容差、自动优化、物理反向设计与ML反向预测均保留且ML路径调用代理模型粗搜索 | **PASS** | — |
| 实验验证 | 实验/仿真定量比较与误差指标保留 | **PASS** | — |
| 代理模型构建/正向预测 | RF、XGBoost、BiLSTM 与 数据→训练→比较→预测 链路保留 | **PASS** | — |
| 模型解释 | SHAP/特征贡献解释能力保留且与物理失配概念分开 | **PASS** | — |
| 教学 | 五大失配、2D/3D/自由实验保留；器件/仪器不再使用自动吸附式交互 | **PASS** | — |
| 上下文入口 | 完整镜头编辑器和完整结果目录具备真实路由 | **PASS** | — |
| 单一当前系统术语 | 前端不再使用“当前方案/方案A/B”等并行方案语义 | **FAIL** | 残留：frontend_pyside\features\machine_learning\page.py、frontend_pyside\features\optimization\presentation\result_behavior.py、frontend_pyside\shared\plotting\engineering_views.py |

**OVERALL: FAIL**
