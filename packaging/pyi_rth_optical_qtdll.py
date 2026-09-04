"""PyInstaller runtime hook for OpticalMLPlatform.

Freeze-safe: register the bundled binary directories as DLL search paths so
Windows resolves shiboken6.abi3.dll / pyside6.abi3.dll / Qt6Core.dll /
python3.dll / icu*.dll from the bundle.  Without this, ``import
PySide6.QtCore`` can fail with "DLL load failed ... 找不到指定的程序"
because the frozen layout splits binaries across ``_internal``,
``_internal/PySide6`` and ``_internal/shiboken6`` while the extension-module
loader only searches the .pyd's own directory plus registered DLL directories.
"""

import os
import sys
from pathlib import Path


def register_dll_dirs() -> None:
    if not getattr(sys, "frozen", False):
        return
    base = Path(getattr(sys, "_MEIPASS", None) or Path(sys.executable).resolve().parent)
    for folder in ("", "PySide6", "shiboken6"):
        candidate = base / folder if folder else base
        try:
            if candidate.is_dir():
                os.add_dll_directory(str(candidate))
        except Exception:
            pass


def prepend_bundle_path() -> None:
    if not getattr(sys, "frozen", False):
        return
    base = Path(getattr(sys, "_MEIPASS", None) or Path(sys.executable).resolve().parent)
    entries = [str(base), str(base / "PySide6")]
    current = os.environ.get("PATH", "")
    existing = [part for part in current.split(os.pathsep) if part]
    merged = entries + [part for part in existing if part not in entries]
    os.environ["PATH"] = os.pathsep.join(merged)


register_dll_dirs()
prepend_bundle_path()
