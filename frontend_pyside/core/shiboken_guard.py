"""shiboken 签名特性钩子加固（six.moves 兼容）。

six 的惰性子模块（six.moves._thread 等）没有 ``__file__``，shiboken 的
``_mod_uses_pyside`` 在 ``raise TypeError('{!r}'...)`` 格式化模块对象时会
再抛 AttributeError，逃过其 ``except TypeError`` 分支 —— 任何在
``import PySide6`` 之后发生的 ``dateutil``（sklearn/pandas 链）导入都会崩。
本模块给钩子加兜底：检查失败一律视为"不使用 PySide"，仅放弃签名注入。

用法：在 import PySide6 之后、可能触发 dateutil/six 的导入之前调用
``harden_shiboken_signature_hook()``（幂等，可重复调用）。
"""

from __future__ import annotations


def harden_shiboken_signature_hook() -> bool:
    try:
        import shibokensupport.feature as _feature
    except Exception:
        return False
    original = getattr(_feature, "_mod_uses_pyside", None)
    if original is None or getattr(original, "_shiboken_guarded", False):
        return True

    def _guarded_uses_pyside(module):
        try:
            return original(module)
        except Exception:
            return False

    _guarded_uses_pyside._shiboken_guarded = True
    _feature._mod_uses_pyside = _guarded_uses_pyside
    return True
