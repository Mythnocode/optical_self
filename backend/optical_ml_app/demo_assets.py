from __future__ import annotations

import json
import os
import shutil
from pathlib import Path


def _copy_tree_if_missing(source: Path, target: Path) -> bool:
    if target.exists() or not source.is_dir():
        return False
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(source, target, copy_function=shutil.copy2)
    return True


def install_packaged_demo_assets(user_data_dir: Path) -> dict[str, object]:
    """Install small, real-pipeline demo assets without adopting them as current state.

    The bundle is intentionally small enough to ship with the app.  It is labelled as
    示例 data/model in its manifests and is copied only when the same IDs are absent.
    User-created assets are never overwritten.  Set INSTALL_DEMO_ASSETS=0 to disable.
    """
    if os.getenv("INSTALL_DEMO_ASSETS", "1").strip().lower() in {"0", "false", "no", "off"}:
        return {"enabled": False, "installed": []}
    project_root = Path(__file__).resolve().parents[2]
    bundle = project_root / "resources" / "demo_assets" / "quick_real_780nm"
    if not bundle.is_dir():
        return {"enabled": True, "installed": []}
    installed: list[str] = []
    for source in sorted((bundle / "datasets").iterdir() if (bundle / "datasets").is_dir() else []):
        if source.is_dir() and _copy_tree_if_missing(source, Path(user_data_dir) / "datasets" / source.name):
            installed.append(f"dataset:{source.name}")
    for source in sorted((bundle / "models").iterdir() if (bundle / "models").is_dir() else []):
        if source.is_dir() and _copy_tree_if_missing(source, Path(user_data_dir) / "models" / source.name):
            installed.append(f"model:{source.name}")
    cache_target = Path(user_data_dir) / "cache" / "shap"
    cache_target.mkdir(parents=True, exist_ok=True)
    for source in sorted((bundle / "shap").glob("*.json")):
        target = cache_target / source.name
        if not target.exists():
            shutil.copy2(source, target)
            installed.append(f"shap:{source.name}")
    info = {"enabled": True, "installed": installed}
    try:
        info["bundle"] = json.loads((bundle / "bundle.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        pass
    return info


__all__ = ["install_packaged_demo_assets"]
