from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from PySide6.QtCore import QUrl
from PySide6.QtQml import QQmlComponent, QQmlEngine
from PySide6.QtWidgets import QApplication

from frontend_pyside.features.teaching.asset_registry import ASSETS, FALLBACK_ASSET


def main() -> int:
    app = QApplication.instance() or QApplication([])
    engine = QQmlEngine()
    qml_root = ROOT / 'frontend_pyside/resources/qml/teaching3d'
    seen = []
    rows = []
    failed = 0
    for asset in list(ASSETS.values()) + [FALLBACK_ASSET]:
        if asset.qml in seen:
            continue
        seen.append(asset.qml)
        path = qml_root / asset.qml
        component = QQmlComponent(engine, QUrl.fromLocalFile(str(path)))
        obj = component.create()
        errors = [item.toString() for item in component.errors()]
        status = 'PASS' if obj is not None and not errors else 'FAIL'
        if status == 'FAIL':
            failed += 1
        rows.append({'qml': asset.qml, 'status': status, 'errors': errors})
        if obj is not None:
            obj.deleteLater()
        app.processEvents()
    report = {
        'generated_at': datetime.now(timezone.utc).isoformat(),
        'platform': os.environ.get('QT_QPA_PLATFORM', ''),
        'unique_asset_qml_count': len(rows),
        'failed': failed,
        'assets': rows,
    }
    out = ROOT / 'assets_3d/reports/teaching_3d_qml_asset_validation.json'
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 1 if failed else 0


if __name__ == '__main__':
    raise SystemExit(main())
