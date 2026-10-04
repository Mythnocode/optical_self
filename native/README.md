# native — 多线程光线追迹 C++ 内核

## 背景

数据生成 / 扫描 / 优化的单样本仿真中，约 90% 时间消耗在
`optical_core.physics.geometric.solvers.scalar_raytrace.trace_single_ray_detailed`
的纯 Python 逐光线循环（每光线逐表面的小向量 NumPy 运算 + Ray 对象构造）。
该代码被 GIL 锁死，Python 线程无法加速（这正是旧基准
"开 4 线程反而更慢" 的真实原因——当时把瓶颈误判为 FFT/内存带宽）。

本目录把 full 追迹语义逐行移植为 C++（`optical_native_core.cpp`），
按光线并行（常驻线程池），通过 C ABI + ctypes 调用：

```
前端"生成数据集" → 后端 DatasetGenerator → engine.evaluate
  → context.get_or_create_trace → batch_raytrace.trace_ray_batch
      → native_trace.trace_ray_batch_native   ← C++ DLL（新增，失败自动回退）
```

## 构建

```
native\build.bat            # 需要 MinGW-w64 g++（仓库宿主已有 8.1.0）
```

产物 `native\build\optical_native.dll`（静态链接 libgcc/libstdc++，无额外 DLL 依赖）。

## 运行时开关

| 环境变量 | 含义 |
| --- | --- |
| `OPTICAL_NATIVE_DLL` | 覆盖 DLL 路径 |
| `OPTICAL_NATIVE=0` | 强制关闭原生路径（回退 Python full tracer） |
| `OPTICAL_NATIVE_THREADS` | 工作线程数；默认自动（CPU 逻辑核数，上限 32；小批次自动内联） |

## 语义边界（自动回退 Python 路径的情形）

- DLL 未编译/加载失败
- 光栅表面（grating）——需要分叉追迹，走 Python
- `include_group_delay`——镀膜群延迟需要 Python 的 unwrap 逻辑
- 内核运行时遇到无法复刻的异常路径（如入射角越界），整批回退

## 验证

`tests/test_native_raytrace_parity.py`：

- TraceBundle 全字段一致性（位置/方向/光程/振幅/功率/偏振/相位/分段/路径/状态码/终止原因）
- 表面记录与逐表面交互诊断数值一致
- 引擎端到端耦合指标一致（rel 1e-7）
- 无效光线输入行为一致

## 基准（i7-13700HX，441 光线 × 8 镀膜表面）

| 实现 | 耗时 |
| --- | --- |
| Python full tracer | ~1540 ms |
| C++ 单线程 | ~17 ms |
| C++ 线程池（自动） | ~13 ms |

整体热路径加速约 **100×**；数据生成单样本从 ~5.4 s 降至亚秒级
（剩余时间为波动光学传播与耦合计算）。

## 2026-10-01 数据集调用链确认

`dataset_simulation_options()` 在 geometric/hybrid 组显式设置
`prefer_native_trace=True`，上下文将其传入 `TraceOptions.prefer_native`。
因此数据集追迹优先调用现有 C++ DLL；其他仿真沿用原来的路径选择。
原生不可用、显式关闭或系统不受支持时，继续尝试 NumPy compact / Python full。
波动传播、FFT、耦合及质量门槛仍使用原实现，不降低采样精度。

生成样本的 `metadata.trace_backends` 与 manifest 的
`metadata.trace_backend_sample_counts` 记录实际后端；后者按最终样本计数，
不包含高精度重试的独立调用次数，同一样本可能出现多个后端。

本机单次端到端基准（默认四镜片、8个有效样本目标、seed99、standard、单样本工作器）：

| 系统 / 实际路径 | 总耗时 | 追迹耗时 / 次数 | 有效 / 失败 |
| --- | ---: | ---: | ---: |
| 带镀膜 / Python full（关闭 native） | 220.262 s | 202.484 s / 24 | 8 / 8 |
| 带镀膜 / C++ | 19.302 s | 1.904 s / 24 | 8 / 8 |
| 无镀膜 / NumPy compact | 13.154 s | 0.636 s / 24 | 8 / 8 |
| 无镀膜 / C++（compact记录） | 14.940 s | 0.427 s / 24 | 8 / 8 |

带镀膜案例端到端约11.41倍、追迹约106.34倍。C++不保证每种系统都更快；
无镀膜案例原生追迹约1.49倍，但端到端仍比 NumPy 慢约1.79秒，后续需重复测量
波动传播/审计的耗时。原生 compact 记录省去与旧 compact 同样不提供的 Python
逐光线交互字典，保留实际计算的功率、场、表面数据；full、镀膜、位姿系统仍保留完整记录。
两组样本有效性、划分、输入特征一致，
标签最大绝对差分别8.20e-13 / 1.10e-10。
这是单次本机测量，不是跨机器性能保证。

复现并保留证据：
`D:/python/python3.12/python.exe tools/benchmark_dataset_backends.py production 8`；
关闭 native 对照用 `compact 8`（带镀膜不支持 compact，实际落到 Python full）；
无镀膜追加 `uncoated`。
运行 `tools/compare_dataset_backends.py compact-8 production-8` 比较标签。
报告及样本保存在 `tests/golden/dataset-backends/`，脚本不删除输出。

真实 Web 序列生成任务 `job-3bc1d93e5c4a` 完成，manifest 显示150个样本均
`cpp_native`，14有效 /136失败，序列CSV已导出。目标50未达到，不能将部分
有效数据宣称为50个有效系统。

2026-10-02 的 Windows 安装包已包含同一份 DLL（SHA256
`6ab259003daf527db3dd9d3b5565af77342a3482806e44507b8be3641996566d`），
无需用户安装 C++ 编译器。安装后的实际任务 `job-1e69eeb75777` 产生8有效/17尝试，
17个最终样本均记录 `cpp_native`，与开发环境参考的输入、标签、质量判断一致。
DLL 未重新编译；详见 `docs/migration/desktop-packaging.md`。
