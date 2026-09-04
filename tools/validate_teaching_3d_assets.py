from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from frontend_pyside.features.teaching.asset_registry import ASSETS, FALLBACK_ASSET
from frontend_pyside.features.teaching.component_catalog import DRAWING_SCHEMES

MODEL_RE = re.compile(r"\bModel\s*\{")
TRANSPARENT_RE = re.compile(r"alphaMode\s*:\s*PrincipledMaterial\.Blend")
FORBIDDEN_RE = re.compile(r"\b(?:PerspectiveCamera|OrthographicCamera|DirectionalLight|PointLight|SpotLight)\s*\{")


def inspect_asset(kind: str, asset) -> dict[str, object]:
    qml_path = ROOT / "frontend_pyside" / "resources" / "qml" / "teaching3d" / asset.qml
    errors: list[str] = []
    warnings: list[str] = []
    text = ""
    if not qml_path.is_file():
        errors.append(f"missing qml: {qml_path.relative_to(ROOT)}")
    else:
        text = qml_path.read_text(encoding="utf-8")
    model_count = len(MODEL_RE.findall(text))
    transparent_count = len(TRANSPARENT_RE.findall(text))
    if FORBIDDEN_RE.search(text):
        errors.append("asset contains camera/light; lighting belongs to the scene")
    if "sceneBridge." in text:
        errors.append("visual asset references sceneBridge/physics state")
    if "pickable: true" in text:
        errors.append("visual asset is pickable; picking must use the cheap proxy")
    limit = 8 if asset.tier == "A" else 12
    if model_count > limit:
        errors.append(f"model count {model_count} exceeds tier {asset.tier} limit {limit}")
    if model_count != asset.estimated_models:
        warnings.append(f"registry estimated_models={asset.estimated_models}, actual={model_count}")
    if transparent_count != asset.transparent_materials:
        warnings.append(
            f"registry transparent_materials={asset.transparent_materials}, actual={transparent_count}"
        )
    if any(value <= 0 for value in asset.pick_scale):
        errors.append("pick proxy scale must be positive")
    return {
        "kind": kind,
        "asset": asdict(asset),
        "qml_exists": qml_path.is_file(),
        "models": model_count,
        "transparent_materials": transparent_count,
        "errors": errors,
        "warnings": warnings,
        "status": "FAIL" if errors else ("WARN" if warnings else "PASS"),
    }


def build_report() -> dict[str, object]:
    rows = [inspect_asset(kind, asset) for kind, asset in sorted(ASSETS.items())]
    fallback = inspect_asset("__fallback__", FALLBACK_ASSET)
    catalog_missing = sorted(set(DRAWING_SCHEMES) - set(ASSETS))
    gate_errors: list[str] = []
    if catalog_missing:
        gate_errors.append("catalog kinds missing explicit 3D assets: " + ", ".join(catalog_missing))
    proxy_path = ROOT / "frontend_pyside/resources/qml/teaching3d/OpticalAssetNode.qml"
    proxy_text = proxy_path.read_text(encoding="utf-8") if proxy_path.is_file() else ""
    if proxy_text.count("pickable: true") != 1:
        gate_errors.append("OpticalAssetNode must expose exactly one pickable proxy")
    if "Loader3D" not in proxy_text:
        gate_errors.append("OpticalAssetNode must use Loader3D for visual assets")
    if "dragOwner" not in proxy_text:
        gate_errors.append("pick proxy must expose dragOwner")
    failed = [row for row in rows + [fallback] if row["status"] == "FAIL"]
    warnings = [row for row in rows + [fallback] if row["warnings"]]
    status = "FAIL" if gate_errors or failed else ("WARN" if warnings else "PASS")
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "status": status,
        "principle": "3D visual assets are isolated from optical physics",
        "catalog_coverage": {
            "catalog_kinds": len(DRAWING_SCHEMES),
            "explicit_assets": len(ASSETS),
            "missing": catalog_missing,
        },
        "interaction_gate": {
            "single_pick_proxy": proxy_text.count("pickable: true") == 1,
            "loader3d": "Loader3D" in proxy_text,
            "drag_owner": "dragOwner" in proxy_text,
        },
        "gate_errors": gate_errors,
        "assets": rows,
        "fallback": fallback,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--output",
        type=Path,
        default=ROOT / "assets_3d/reports/teaching_3d_asset_gate.json",
    )
    args = parser.parse_args()
    report = build_report()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({
        "status": report["status"],
        "catalog_coverage": report["catalog_coverage"],
        "gate_errors": report["gate_errors"],
        "report": str(args.output),
    }, ensure_ascii=False, indent=2))
    for row in report["assets"]:
        print(f"{row['status']:4} {row['kind']:20} models={row['models']} transparent={row['transparent_materials']}")
        for item in row["errors"]:
            print("  ERROR", item)
        for item in row["warnings"]:
            print("  WARN ", item)
    return 1 if report["status"] == "FAIL" else 0


if __name__ == "__main__":
    raise SystemExit(main())
