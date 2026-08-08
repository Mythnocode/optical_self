from __future__ import annotations

import faulthandler
from importlib.util import find_spec
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _check_runtime() -> None:

    required = {
        "PySide6": "PySide6",
        "PySide6.QtWidgets": "PySide6-Essentials",
        "PySide6.QtWebSockets": "PySide6-Addons",
        "PySide6.QtSvg": "PySide6-Addons",
        "shiboken6": "shiboken6",
        "numpy": "numpy",
        "scipy": "scipy",
        "pandas": "pandas",
        "matplotlib": "matplotlib",
        "cycler": "cycler",
        "openpyxl": "openpyxl",
        "sklearn": "scikit-learn",
        "shap": "shap",
        "xgboost": "xgboost",
        "torch": "torch",
        "joblib": "joblib",
        "cloudpickle": "cloudpickle",
        "threadpoolctl": "threadpoolctl",
        "fastapi": "fastapi",
        "uvicorn": "uvicorn",
        "websockets": "websockets",
        "httpx": "httpx",
        "pydantic": "pydantic",
        "yaml": "PyYAML",
    }
    missing = []
    for module, package in required.items():
        try:
            available = find_spec(module) is not None
        except (ImportError, ModuleNotFoundError):
            available = False
        if not available and package not in missing:
            missing.append(package)
    if missing:
        print("程序运行依赖不完整：" + "、".join(missing))
        print(f"当前 Python：{sys.executable}")
        print("请在项目根目录运行：")
        print("  python -m pip install -r requirements/requirements.txt")
        raise SystemExit(2)


if __name__ == "__main__":
    faulthandler.enable()
    from frontend_pyside.app.startup import configure_process_environment

    configure_process_environment()
    _check_runtime()
    from frontend_pyside.app.main import main

    raise SystemExit(main())
