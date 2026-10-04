# 数据集页面与 C++ 计算调用链（2026-10-01）

分支 `js`。完整迁移尚未完成。本页记录本阶段已经实现的内容及实际证据。

2026-10-02 补充：后端连接恢复后重新读取数据集列表和生成参数，保持已填写选项。
当前 C++ DLL 可加载，已有数据集 manifest 再次确认17个最终样本为 `cpp_native`。
本次没有重新生成数据集；详见 [backend-diagnostics.md](backend-diagnostics.md)。

## 2026-10-02：正常表单的视觉修正

本节覆盖下文旧的九状态布局结论。修正数据集专用左栏宽度292px、正文起点293px、
外边距12/10px、分组边框与圆角，以及生成、训练、导入和数值控件的字体。
滚动区域放在外边距内，滑块颜色沿用原版最终QSS的 `#667085`。
变量复选框的正常勾选/未勾选图样由原版Qt Fusion直接渲染为1/1.5/2倍PNG，
Web仍使用真实checkbox输入；仅运行时展示这些静态资源，不依赖Qt。

原版 `capture-dataset-baseline.py --visual-only` 在隔离环境离屏捕获，
不会提交生成或训练任务。新增尺寸、缩放与字体/框架元数据选项。
Web通过真实页面切换导入、固定/任意镜头数、训练和生成参数展开状态。

| 逻辑窗口尺寸 | 状态 | 控件观测 | 最大矩形差 | 字体族/字号/字重差项 |
| --- | ---: | ---: | ---: | ---: |
| 1280×800 | 9 | 224 | 0.041687px | 0 |
| 1440×900 | 9 | 224 | 0.041687px | 0 |

两种尺寸都无文字/控件缺项，导航、正文、两组表单和左栏框架最大差约0.021px。
全部截图已用视觉模型查看；由此发现并修正了浏览器蓝色复选框和较浅滚动条。
字体族、字号及字重相同并不保证字体栅格相同；输入边框、焦点、导航栅格及
其他DPI/桌面实窗仍需验收，不能宣称整页像素一致。

证据目录：`tests/golden/ui-baseline/dataset-controls/scale-1.5-{1280x800,1440x900}/`
与 `tests/golden/ui-current/dataset-controls/{1280x800,1440x900}/`。
原版150%原始PNG分别为1920×1200/2160×1350；浏览器DPR1.5，但工具输出逻辑尺寸PNG。
`visual-pairs/` 接触图仅对原版用LANCZOS归一化以供人工查看；RGB差值只作诊断。
完整页面包含不同的数据集列表，不能把其差值当作控件像素相等的判据。
`compare-dataset-states.py` 保留默认旧目录，新增路径参数、字体与框架比较及空记录拒绝。
`render-dataset-visual-comparison.py` 只排列已捕获截图，不是自动测试套件。

页面已恢复所选数据集11、生成50样本、固定四透镜、257×257、seed42、
生成参数展开/训练参数收起。本轮没有提交新计算或更改光学项目。
C++ DLL哈希和 `prefer_native_trace=True` 调用保留；Web/Desktop类型检查及构建通过。
本轮源码与Web构建包含视觉修正，现有安装包仍为之前的诊断版本，尚未重新打包。

## 2026-10-02：安装包中的 C++ 链路

Windows 安装包已包含隔离 Python、原有光线追迹 DLL 和科学计算运行库。
安装后的实际任务 `job-1e69eeb75777` 生成8个有效样本，17次尝试均记录
`cpp_native`；特征、标签、有效性和质量判断与开发环境参考逐项相等。
本机安装/卸载及资源完整性检查通过。详见
[desktop-packaging.md](desktop-packaging.md) 和 `tests/golden/desktop-packaging/`。
下文 PID30164 等为历史记录；当前运行环境以 `.ai-memory/handoff.md` 为准。
干净电脑兼容性、正常关窗生命周期和整页视觉一致性仍需验收。

## 2026-10-02：导入复场链路已接通

本节覆盖下文旧检查中的“复场尚不支持”和旧运行进程信息。

- `DatasetGenerationRequest.imported_mode` 携带已读取的实部、虚部、来源及物理窗口。
  方形、奇数、至少17点、有限数值、非零功率在任务创建前校验；缺失复场返回422。
- Web 从原有复场缓存恢复数组，prepare/submit 传递同一份数据；提交前核对项目和
  计算签名，期间编辑会拒绝继续提交。数据集模式不依赖仿真页面是否勾选耦合分析。
- PySide 的原有 `request_options()` 也接到同一字段。普通高斯项目的 prepare
  payload 与此前捕获的原版 payload 完全相等，没有新增空字段。
- 生成器仅序列化复场一次，样本及高精度重试复用数组。保留原复场接收网格、
  原物理窗口，关闭自动扩窗；扩窗会改变复场的形状和物理含义，现有求解器无法
  自动重采样它。传播精度及原有能量、边缘、Nyquist、收敛检查仍按原门槛运行。
  geometric/hybrid 的 `prefer_native_trace=True` 保留，光学核心没有改写。
- manifest 记录复场网格、窗口、SHA256及实际后端；数组不写入每条样本记录。

实际页面生成：

| 任务 | 接收模式 | 结果 |
| --- | --- | --- |
| job-750ccde62dd1 | 当前页面的高斯近似 | 数据集10，8有效/17尝试；17个最终样本均cpp_native，worker 10.933秒 |
| job-4760fdfd18a4 | 选择已有 imported-mode-513.npz | 数据集11/dataset-1620a42e0fce，6有效/24尝试；24个最终样本均cpp_native，worker 128.606秒 |

第二批请求8有效样本，实际没有达到目标。18个失败分别为16个能量检查失败、
2个边缘功率检查失败；没有放宽质量门槛，也没有把这批结果写成8个有效样本。
原始实部、虚部逐项相等，manifest SHA256一致；原生表单复场提取值与该请求相等。
有效prepare往返后整个typed请求相等。缺失复场、非法hybrid、零功率及不匹配网格
均实际返回422；这些检查没有新增任务。CSV下载成功，包含6个有效系统。

证据：`tests/golden/ui-current/dataset/imported-mode/` 中的 job/result/input-summary/
samples/provenance/validation、CSV和截图。`record-imported-dataset-evidence.py` 只记录
已完成的实际任务，读取本机本次任务的重试合同，不是自动测试套件。
预览状态刷新后保留所选数据集；1280×800的收起/展开布局已和原版截图视觉对照。
字体、导航位置和Chromium边框栅格仍存在差异，不能据此宣称整个页面像素一致。
临时复场检查后恢复进入检查时的高斯接收模式，清除本次临时复场引用；没有提交
新的正式仿真或训练任务。当前复场批次的装调值为0，不能沿用旧记录的偏移/倾角。

当前后台PID30164/session93054，Vite session47123。全库迁移仍需完成其他视觉状态、
生命周期、扫描算法与桌面安装包（包括C++ DLL）。下文任务与耗时保留为历史证据。

## 界面和原版请求

- 新界面使用原版导入/生成、固定/任意镜头数、变量方案和精度控件。
- 从原版提取纯展示逻辑到 `shared_presentation/dataset_configuration.py`、
  `variable_rows.py`，旧 PySide 入口保留兼容导出；`dataset_generation.py` 沿用
  原版参数范围和变量解析。光学标签仍由既有 DatasetGenerator 和光学引擎生成。
- API `/datasets/generation/presentation` 返回原版变量标签和实体镜片信息；
  `/datasets/generation/prepare` 生成原有 `DatasetGenerationRequest`；正式生成仍走
  `/dataset/jobs`。不在 JavaScript 中实现光学计算。
- 导入/训练参数、生成选项和任务持久化；生成结束刷新注册表并选择真正的结果。
  任意镜头数列表按 manifest 的 `dataset_layout` 过滤。BiLSTM 使用实际导出的
  sequence CSV 和列映射。
- 界面数值控件与原版一致，不额外显示步进箭头。左栏进度/取消行及16px状态图标
  使用原版布局和 SVG。去除了原版没有的常驻数据集详情面板。

原版实际提交 payload 由 `scripts/capture-dataset-baseline.py` 捕获；
`compare-dataset-generation-requests.py` 对当前 prepare API 的固定/序列两种
payload 全字段比较均一致。固定最低8样本、序列最低10样本。

9个静态状态覆盖224个可见控件，没有数量/文字缺项，最大矩形差0.041687px。
`tests/golden/ui-{baseline,current}/dataset/` 保存截图、geometry 和比较报告。
该几何结论不等于像素完全相同：字体、焦点边框和活动行栅格仍有差异；
页面仅在1280×800进行本轮验收，其他尺寸/高DPI待验收。
最后按原版QSS修正顶栏650字重、17px说明文字、650字重变量按钮、隐藏按钮箭头、
训练数值字体，并重新捕获9种状态；没有宣称全部像素一致。

## 实际生成和训练

| 任务 | 结果 |
| --- | --- |
| job-75801233b310 | 原导入复场项目生成，0有效/24尝试；现有生成器没有 imported_mode_values，不能宣称支持该情况 |
| job-3a320481e992 | 临时高斯接收模式，固定8目标，8有效/9失败 |
| job-4bcca42713cd | 序列10目标，仅4有效，低于原版序列导出门槛，失败 |
| job-d3aeda2d0259 | 序列50目标，14有效/136失败，共150尝试；dataset-45c13896e1dc，CSV导出成功 |
| job-83aa016df115 | 上述实际数据集 BiLSTM 2轮流程检查，完成；9训练/2验证/3测试，不是模型质量验收 |
| job-3a6bb31e97c5 | 旧取消流程在序列导出门槛处错误地失败，已修复 |
| job-3bc1d93e5c4a | 当前 C++ 序列任务完成；dataset-df7db000dc7d（数据集6），150尝试均记录cpp_native，14有效/136失败，worker_compute55.839秒 |
| job-758a8b9c1dae | 实际页面取消1000样本任务，最终cancelled且无错误；跳过取消后的序列导出门槛 |

本轮没有提交新的 Simulation。生成检查时将接收模式临时设为单模/高斯，结束时已恢复
用户模式/导入复场及 `imported-mode-513-replacement.npz`（513×513，780nm）。
保留源项目数值及最后提交的 Simulation/Teaching 合同。后端可能还有用户另外提交的
任务，不能假定所有最近任务均由本轮浏览器创建。

## C++

已有 `native/optical_native_core.cpp` 与可加载的 `native/build/optical_native.dll`。
先前 full 路径已能调用 C++，但 compact 可用时优先 NumPy。
现在数据集在 geometric/hybrid 组选项明确设置 `prefer_native_trace=True`，
进入 `TraceOptions.prefer_native`；正式仿真的默认路径选择保持原样。
DLL不可用、显式关闭或不支持的系统继续回退既有实现。

原生 compact 输出对普通无镀膜系统省去旧 compact 同样不提供的 Python 交互审计字典；
不省略实际表面物理、功率或场计算。full、镀膜和位姿系统仍提供全部审计记录。
样本 `metadata.trace_backends` 和 manifest `trace_backend_sample_counts` 记录实际后端。
单个最终样本的计数不包含高精度重试的额外调用，不是总追迹次数。

本机单次测量：默认四镜片/seed99/standard/8有效样本目标，16尝试/24追迹，
两边均8有效/8失败；带镀膜 Python full220.262秒 → C++19.302秒，约11.41倍；
追迹202.484→1.904秒，约106.34倍。标签最大绝对差8.20e-13。
无镀膜 NumPy13.154秒 / C++ compact14.940秒，原生追迹本身0.427秒 vs NumPy0.636秒；
端到端原生仍慢1.79秒，后续需重复测量传播/审计部分，不能承诺所有系统提速。
输入特征、有效性、划分均一致，无镀膜标签最大差1.10e-10。

`tools/benchmark_dataset_backends.py` 和 `compare_dataset_backends.py` 留存
`tests/golden/dataset-backends/` 的完整报告和样本。初次原生无镀膜完整审计版
耗时19.830秒的报告保存在 `report-before-compact-audit.json`，不隐藏其较慢结果。
现有 DLL 未改动或重新编译；只复用已实现的 C++ 内核及调整数据集调用/记录。
Windows 安装包及 DLL 包含仍待整个迁移的打包阶段完成。

## 运行与后续

- 当前 backend PID20356/session59144，Python3.12，USER_DATA_DIR 为
  `%TEMP%/optical-js-training-20260930`；Vite session87319。
- `run_backend.py` 先绑定8000，再导入/构建服务图，防止重复启动在端口冲突前修改
  活跃任务的恢复状态。当前正常启动已成功；并发启动竞争尚未专门验收。
- typecheck/build/diff-check通过；没有运行自动测试套件。Three块600.12kB警告仍在。
- 下一步：宽屏/高DPI/顶栏字重与边框、任务恢复失败、生成时项目切换竞态、导入复场
  数据集能力、Optimization/Explainability以及桌面打包。完整迁移目标保持active。
