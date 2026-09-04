from __future__ import annotations

import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from PySide6.QtCore import QObject
from PySide6.QtQuick import QSGRendererInterface
from PySide6.QtWidgets import QApplication

from frontend_pyside.features.teaching.unified_quick3d import UnifiedTeachingQuick3DView
from frontend_pyside.features.teaching.unified_workbench import ExperimentModel


def main() -> int:
    app = QApplication.instance() or QApplication([])
    model = ExperimentModel()
    view = UnifiedTeachingQuick3DView()
    view.resize(1280, 720)
    view.set_model(model)
    view.show()
    for _ in range(30):
        app.processEvents()
        time.sleep(0.02)

    errors = view.qml_errors()
    api = view._quick.quickWindow().rendererInterface().graphicsApi()
    api_name = getattr(api, 'name', str(api))
    quick3d_available = api not in {
        QSGRendererInterface.GraphicsApi.Unknown,
        QSGRendererInterface.GraphicsApi.Software,
        QSGRendererInterface.GraphicsApi.Null,
    }
    asset_nodes = []
    root_object = view._quick.rootObject()
    if root_object is not None:
        for child in root_object.findChildren(QObject):
            name = child.objectName()
            if name.startswith('asset:'):
                asset_nodes.append({
                    'object': name,
                    'asset_load_failed': bool(child.property('assetLoadFailed')),
                })

    report = {
        'generated_at': datetime.now(timezone.utc).isoformat(),
        'platform': os.environ.get('QT_QPA_PLATFORM', ''),
        'renderer_api': api_name,
        'quick3d_render_available': quick3d_available,
        'qml_error_count': len(errors),
        'qml_errors': errors,
        'scene_counts': {
            'nodes': len(view._bridge.nodes),
            'edges': len(view._bridge.edges),
            'envelope_segments': len(view._bridge.envelopeSegments),
        },
        'detailed_assets_enabled': bool(view._bridge.detailedAssetsEnabled),
        'asset_nodes': asset_nodes,
        'asset_node_count': len(asset_nodes),
        'asset_load_failures': sum(1 for item in asset_nodes if item['asset_load_failed']),
    }
    out = ROOT / 'assets_3d/reports/teaching_3d_qml_smoke.json'
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(report, ensure_ascii=False, indent=2))
    print('report:', out)
    view.close()
    app.processEvents()
    return 1 if errors else 0


if __name__ == '__main__':
    raise SystemExit(main())
