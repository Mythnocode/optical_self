# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for OpticalMLPlatform.

Build from repo root:
    D:\\anacondanew\\envs\\optical\\python.exe -m PyInstaller --noconfirm --clean packaging/optical_ml.spec
"""

from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files, collect_submodules

SPEC_DIR = Path(SPECPATH).resolve()
REPO_ROOT = SPEC_DIR.parent

APP_PACKAGES = [
    "backend",
    "frontend_pyside",
    "machine_learning",
    "optical_core",
    "optical_runtime",
    "shared_contracts",
    "shared_ports",
    "teaching_runtime",
    "help_runtime",
]

hiddenimports = []
for package in APP_PACKAGES:
    hiddenimports += collect_submodules(package)

hiddenimports += [
    "uvicorn.logging",
    "uvicorn.loops.auto",
    "uvicorn.protocols.http.auto",
    "uvicorn.protocols.websockets.auto",
    "uvicorn.protocols.websockets.websockets_impl",
    "uvicorn.lifespan.on",
    "PySide6.QtWebSockets",
    "PySide6.QtSvg",
    "PySide6.QtOpenGL",
    "PySide6.QtQml",
    "PySide6.QtQuick",
    "PySide6.QtQuick3D",
    "PySide6.QtQuickWidgets",
    "openpyxl",
    "pandas.io.excel._openpyxl",
    "matplotlib.backends.backend_qtagg",
    "shap",
]

datas = [
    (str(REPO_ROOT / "resources"), "resources"),
    (str(REPO_ROOT / "data_templates"), "data_templates"),
    (str(REPO_ROOT / "assets_3d"), "assets_3d"),
]
datas += collect_data_files("optical_core")
datas += collect_data_files("frontend_pyside", excludes=["__pycache__"])

a = Analysis(
    [str(REPO_ROOT / "launch.py")],
    pathex=[str(REPO_ROOT)],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[str(SPEC_DIR / "pyi_rth_optical_qtdll.py")],
    excludes=[],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="OpticalMLPlatform",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=str(SPEC_DIR / "app.ico"),
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="OpticalMLPlatform",
)
