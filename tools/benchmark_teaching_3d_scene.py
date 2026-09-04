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

from frontend_pyside.features.teaching.asset_registry import asset_for_kind
from frontend_pyside.features.teaching.unified_quick3d import _Unified3DBridge
from frontend_pyside.features.teaching.unified_workbench import ExperimentModel


def current_rss_mb() -> float:
    try:
        pages = int(Path('/proc/self/statm').read_text().split()[1])
        return pages * os.sysconf('SC_PAGE_SIZE') / (1024 * 1024)
    except Exception:
        return 0.0


def estimate_scene_drawables(model: ExperimentModel, bridge: _Unified3DBridge) -> dict[str, int]:
    device_models = sum(asset_for_kind(node.kind).estimated_models for node in model.nodes.values())
    pick_proxies = len(model.nodes)
    selected_halo = 1 if model.selected_node_id else 0
    beam_models = len(bridge.edges)
    envelope_models = len(bridge.envelopeSegments)
    scene_fixed = 4  # board, axis, cross-section, minimal fixed visual budget
    detailed = device_models + pick_proxies + selected_halo + beam_models + envelope_models + scene_fixed
    simplified = len(model.nodes) + pick_proxies + selected_halo + beam_models + envelope_models + scene_fixed
    return {
        'device_visual_models': device_models,
        'pick_proxies': pick_proxies,
        'beam_models': beam_models,
        'envelope_models': envelope_models,
        'estimated_detailed_drawables': detailed,
        'estimated_simplified_drawables': simplified,
    }


def main() -> int:
    model = ExperimentModel()
    bridge = _Unified3DBridge()
    snapshot = model.scene_snapshot()
    t0 = time.perf_counter()
    bridge.set_scene(model, snapshot)
    first_set_ms = (time.perf_counter() - t0) * 1000

    iterations = 500
    t0 = time.perf_counter()
    for _ in range(iterations):
        bridge.set_scene(model, snapshot)
    repeated_ms = (time.perf_counter() - t0) * 1000

    before_revision = model.revision
    before_metrics = model.evaluate()
    for _ in range(100):
        bridge.setDetailedAssetsEnabled(False)
        bridge.setDetailedAssetsEnabled(True)
    physics_unchanged = model.revision == before_revision and model.evaluate() == before_metrics

    rss_before = current_rss_mb()
    # Exercise scene list rebuilding without constructing new physics state.
    for _ in range(1000):
        bridge.set_scene(model, snapshot)
    rss_after = current_rss_mb()

    report = {
        'generated_at': datetime.now(timezone.utc).isoformat(),
        'environment': {
            'qt_qpa_platform': os.environ.get('QT_QPA_PLATFORM', ''),
            'qsg_rhi_backend': os.environ.get('QSG_RHI_BACKEND', ''),
        },
        'scene': {
            'nodes': len(bridge.nodes),
            'edges': len(bridge.edges),
            'envelope_segments': len(bridge.envelopeSegments),
            **estimate_scene_drawables(model, bridge),
        },
        'update_performance': {
            'first_set_scene_ms': round(first_set_ms, 4),
            'repeated_iterations': iterations,
            'repeated_total_ms': round(repeated_ms, 4),
            'mean_set_scene_ms': round(repeated_ms / iterations, 4),
        },
        'memory_probe': {
            'rss_before_mb': round(rss_before, 3),
            'rss_after_mb': round(rss_after, 3),
            'rss_delta_mb': round(rss_after - rss_before, 3),
            'iterations': 1000,
        },
        'physics_invariance': {
            'revision_unchanged': model.revision == before_revision,
            'metrics_unchanged': model.evaluate() == before_metrics,
            'pass': physics_unchanged,
        },
        'note': 'Drawable counts are an engineering estimate. Real GPU FPS/RenderStats require a QRhi-capable desktop renderer.',
    }
    out = ROOT / 'assets_3d/reports/teaching_3d_scene_benchmark.json'
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(report, ensure_ascii=False, indent=2))
    print('report:', out)
    return 0 if physics_unchanged else 1


if __name__ == '__main__':
    raise SystemExit(main())
