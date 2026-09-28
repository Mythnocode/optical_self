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
