
"""仿真结果适配器包。

这里负责把后端结果转换为前端绘图、诊断和结果文档能够消费的结构化数据，
不直接创建 Qt 控件或执行具体的 Matplotlib/QImage 绘制。
"""

from __future__ import annotations

from importlib import import_module

_EXPORTS = {
    "formal_result_to_plots": (".formal_results", "formal_result_to_plots"),
    "formal_ray_dataset_from_result": (".formal_results", "formal_ray_dataset_from_result"),
    "formal_ray_views": (".formal_results", "formal_ray_views"),
    "formal_result_diagnostics": (".formal_results", "formal_result_diagnostics"),
    "preview_result_to_plots": (".formal_results", "preview_result_to_plots"),
}


def __getattr__(name: str):
    target = _EXPORTS.get(name)
    if target is None:
        raise AttributeError(name)
    module_name, attr_name = target
    value = getattr(import_module(module_name, __name__), attr_name)
    globals()[name] = value
    return value


__all__ = list(_EXPORTS)
