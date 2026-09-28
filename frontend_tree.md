frontend_pyside/
├─ app/                              # 应用壳层、主窗口、一级入口编排
│  ├─ main.py
│  ├─ bootstrap.py
│  ├─ startup.py
│  ├─ main_window.py
│  ├─ main_window_layout.py
│  ├─ shell_catalog.py
│  ├─ shell_controller.py
│  ├─ workbench_shell.py             # 主工作台壳层
│  ├─ workbench_jobs.py              # 任务调度
│  └─ workbench_payloads.py           # 数据载荷处理
│
├─ modules/                          # 一级入口模块，主要页面代码在这里
│  ├─ navigation.py                  # 汇总所有一级入口
│  ├─ page_spec.py                   # 页面定义结构
│  ├─ shared.py                      # 模块间公共辅助代码
│  │
│  ├─ home/                          # 首页
│  │  ├─ catalog.py                  # 首页二级功能
│  │  └─ shell.py                    # 首页界面
│  │
│  ├─ simulation/                    # 仿真
│  │  ├─ catalog.py                  # 仿真二级功能栏
│  │  ├─ lens_data.py                # 镜头数据
│  │  ├─ materials.py                # 材料库
│  │  ├─ layout.py                   # 光路图
│  │  ├─ image_quality.py            # 图像质量
│  │  ├─ fiber_coupling.py           # 光纤耦合
│  │  ├─ wave_diffraction.py         # 波前与衍射
│  │  ├─ controls.py                 # 仿真对象侧控件
│  │  ├─ documents.py                # 仿真公共文档组件
│  │  ├─ results.py                  # 仿真结果
│  │  └─ settings.py                 # 仿真设置
│  │
│  ├─ teaching/                      # 教学
│  │  ├─ catalog.py                  # 教学二级功能
│  │  └─ shell.py                    # 教学界面
│  │
│  ├─ model/                         # 建模
│  │  ├─ catalog.py                  # 建模二级功能
│  │  ├─ dataset.py                  # 数据集
│  │  ├─ training_result.py          # 训练结果
│  │  ├─ prediction.py               # 预测
│  │  ├─ documents.py                # 建模公共页面组件
│  │  └─ options.py                  # 建模选项
│  │
│  ├─ optimization/                  # 优化
│  │  ├─ catalog.py                  # 优化二级功能
│  │  ├─ scan.py                     # 扫描优化
│  │  ├─ variables.py                # 优化变量
│  │  ├─ result.py                   # 优化结果
│  │  ├─ documents.py                # 优化公共页面组件
│  │  ├─ goal.py                     # 优化目标
│  │  └─ options.py                  # 优化选项
│  │
│  └─ explainability/                # 可解释性
│     ├─ catalog.py                  # 可解释性二级功能
│     ├─ global_contrib.py           # 全局贡献
│     ├─ param_trend.py              # 参数趋势
│     ├─ current_system.py           # 当前系统解释
│     └─ documents.py                # 可解释性公共页面组件
│
├─ features/                         # 底层业务能力和算法实现
│  ├─ simulation/
│  ├─ machine_learning/
│  ├─ optimization/
│  ├─ explainability/
│  ├─ teaching/
│  ├─ teaching_v2/
│  ├─ home/
│  └─ assistant/
│
├─ shared/                           # 跨页面公共组件和绘图基础设施
│  ├─ components/
│  ├─ dialogs/
│  ├─ layouts/
│  ├─ plotting/
│  ├─ icons.py
│  ├─ feature_labels.py
│  ├─ layout_tokens.py
│  ├─ lazy_widgets.py
│  ├─ lifecycle.py
│  ├─ settings.py
│  └─ utils/
│
├─ api/                              # 后端接口
├─ core/                             # 核心常量和基础定义
├─ infrastructure/                  # 基础设施
├─ models/                           # 数据模型
├─ presets/                          # 预设配置
├─ resources/                        # 图标、主题等资源
├─ state/                             # 应用状态
├─ viewmodels/                        # 状态适配和视图模型
├─ widgets/                           # 通用控件
└─ workers/                           # 异步工作线程