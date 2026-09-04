#!/usr/bin/env python3
"""Interactive Qt Quick 3D acceptance gate for the teaching center.

This tool intentionally drives the real QML MouseArea with QtTest events.  It is
not a unit-test substitute: it verifies renderer selection, detailed-asset loading,
3D picking, drag/commit behavior, camera orbit/pan/wheel navigation, screenshots,
and renderer statistics in one repeatable run.

For Linux CI without a physical display, run under Xvfb with an xcb-capable Qt
platform.  The report records the graphics API so software/offscreen runs cannot
be mistaken for a target-GPU benchmark.
"""
from __future__ import annotations

import argparse
import gc
import json
import math
import os
import statistics
import sys
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from PySide6.QtCore import (  # noqa: E402
    Q_ARG,
    Q_RETURN_ARG,
    QEventLoop,
    QMetaObject,
    QPoint,
    QPointF,
    QTimer,
    Qt,
)
from PySide6.QtGui import QWheelEvent  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QApplication, QMainWindow  # noqa: E402

from frontend_pyside.features.teaching.unified_quick3d import UnifiedTeachingQuick3DView  # noqa: E402
from frontend_pyside.features.teaching.unified_workbench import ExperimentModel  # noqa: E402


def wait_ms(ms: int) -> None:
    loop = QEventLoop()
    QTimer.singleShot(max(0, int(ms)), loop.quit)
    loop.exec()


def rss_mib() -> float:
    try:
        for line in Path("/proc/self/status").read_text(encoding="utf-8").splitlines():
            if line.startswith("VmRSS:"):
                return float(line.split()[1]) / 1024.0
    except OSError:
        pass
    return 0.0


def qml_invoke(root: Any, method: str, *args: Any) -> Any:
    if not args:
        return QMetaObject.invokeMethod(root, method)
    qargs = [Q_ARG("QVariant", value) for value in args]
    return QMetaObject.invokeMethod(root, method, Q_RETURN_ARG("QVariant"), *qargs)


def qml_call_void(root: Any, method: str, *args: Any) -> bool:
    qargs = [Q_ARG("QVariant", value) for value in args]
    return bool(QMetaObject.invokeMethod(root, method, *qargs))


def screen_point_for(root: Any, node_id: str) -> QPoint:
    root.setProperty("diagnosticNodeId", node_id)
    if not QMetaObject.invokeMethod(root, "refreshDiagnosticNodeScreen"):
        raise RuntimeError("QML diagnostic node projection hook is unavailable")
    point = root.property("diagnosticNodeScreen")
    return QPoint(round(point.x()), round(point.y()))


def pick_name(root: Any, point: QPoint) -> str:
    value = qml_invoke(root, "diagnosticPickName", float(point.x()), float(point.y()))
    return str(value or "")


def save_window(window: QMainWindow, path: Path) -> None:
    pixmap = window.grab()
    if pixmap.isNull() or not pixmap.save(str(path)):
        raise RuntimeError(f"failed to save screenshot: {path}")


def image_metrics(path: Path) -> dict[str, float]:
    from PIL import Image
    import numpy as np

    data = np.asarray(Image.open(path).convert("RGB"), dtype=np.float32)
    return {
        "mean": float(data.mean()),
        "std": float(data.std()),
        "nonwhite_ratio": float((data.mean(axis=2) < 248.0).mean()),
    }


def image_diff(a: Path, b: Path) -> dict[str, float]:
    from PIL import Image
    import numpy as np

    left = np.asarray(Image.open(a).convert("RGB"), dtype=np.int16)
    right = np.asarray(Image.open(b).convert("RGB"), dtype=np.int16)
    delta = np.abs(left - right)
    pixel_delta = delta.mean(axis=2)
    return {
        "mean_abs": float(delta.mean()),
        "changed_ratio_gt2": float((pixel_delta > 2.0).mean()),
        "changed_ratio_gt8": float((pixel_delta > 8.0).mean()),
    }


def asset_state(root: Any) -> dict[str, Any]:
    objects = root.findChildren(type(root))  # never used; keeps typing happy
    del objects
    from PySide6.QtCore import QObject

    asset_nodes = [obj for obj in root.findChildren(QObject) if obj.objectName().startswith("asset:")]
    return {
        "count": len(asset_nodes),
        "ready": sum(bool(obj.property("visualReady")) for obj in asset_nodes),
        "failed": [obj.objectName() for obj in asset_nodes if bool(obj.property("assetLoadFailed"))],
    }


def render_stats(root: Any) -> dict[str, float | int]:
    keys = {
        "fps": "diagnosticFps",
        "frame_time_ms": "diagnosticFrameTime",
        "render_time_ms": "diagnosticRenderTime",
        "draw_calls": "diagnosticDrawCallCount",
        "draw_vertices": "diagnosticDrawVertexCount",
        "render_passes": "diagnosticRenderPassCount",
        "mesh_mib": "diagnosticMeshDataMiB",
        "image_mib": "diagnosticImageDataMiB",
    }
    result: dict[str, float | int] = {}
    for out_key, prop in keys.items():
        value = root.property(prop)
        if out_key in {"fps", "draw_calls", "draw_vertices", "render_passes"}:
            result[out_key] = int(value or 0)
        else:
            result[out_key] = float(value or 0.0)
    return result


def camera_diag(root: Any) -> dict[str, float]:
    return {
        "pivot_x": float(root.property("diagnosticCameraPivotX")),
        "pivot_y": float(root.property("diagnosticCameraPivotY")),
        "distance": float(root.property("diagnosticCameraDistance")),
        "azimuth": float(root.property("diagnosticCameraAzimuth")),
        "elevation": float(root.property("diagnosticCameraElevation")),
    }


def distance2d(a: dict[str, float], b: dict[str, float], x: str, y: str) -> float:
    return math.hypot(a[x] - b[x], a[y] - b[y])


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=ROOT / "assets_3d/reports/interaction")
    parser.add_argument("--node", default="lens_1")
    parser.add_argument("--width", type=int, default=1200)
    parser.add_argument("--height", type=int, default=760)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)

    app = QApplication.instance() or QApplication(sys.argv)
    window = QMainWindow()
    view = UnifiedTeachingQuick3DView()
    window.setCentralWidget(view)
    window.resize(args.width, args.height)

    model = ExperimentModel()
    # The real teaching workbench uses free mode for direct spatial editing.
    model.mode = "free"
    move_events: list[tuple[str, float, float]] = []

    def commit_move(node_id: str, x: float, y: float) -> None:
        move_events.append((str(node_id), float(x), float(y)))
        model.move_node(node_id, x, y, record=True)
        view.set_model(model)

    view.nodeMoved.connect(commit_move)
    view.set_model(model)
    window.show()
    wait_ms(2600)

    root = view._quick.rootObject()
    if root is None:
        raise RuntimeError("teaching 3D QML root was not created")
    root.setProperty("diagnosticsEnabled", True)
    # Trigger a fresh frame after enabling extended stats.
    view.rotate_camera(0.25)
    wait_ms(350)

    renderer_api = str(view._quick.quickWindow().rendererInterface().graphicsApi())
    qml_errors = [error.toString() for error in view._quick.errors()]
    assets = asset_state(root)
    initial_camera = camera_diag(root)
    initial_revision = model.revision
    initial_scene_xy = (float(model.nodes[args.node].x), float(model.nodes[args.node].y))
    initial_bridge_node = next(item for item in view._bridge.nodes if item["id"] == args.node)
    initial_world_xz = (float(initial_bridge_node["x"]), float(initial_bridge_node["z"]))

    point = screen_point_for(root, args.node)
    picked = pick_name(root, point)

    initial_path = args.output / "01_initial.png"
    drag_path = args.output / "02_drag_mid.png"
    after_path = args.output / "03_drag_after.png"
    orbit_path = args.output / "04_orbit.png"
    pan_path = args.output / "05_pan.png"
    zoom_path = args.output / "06_zoom.png"
    save_window(window, initial_path)

    # --- Real left-button device drag ---------------------------------------
    QTest.mousePress(view._quick, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, point, 40)
    QApplication.processEvents()
    drag_press_ok = bool(root.property("draggingDevice")) and str(root.property("dragId")) == args.node

    drag_samples: list[dict[str, float | int]] = []
    final_point = QPoint(point.x() + 90, point.y() + 25)
    for index in range(1, 7):
        target = QPoint(point.x() + round(90 * index / 6), point.y() + round(25 * index / 6))
        QTest.mouseMove(view._quick, target, 70)
        QApplication.processEvents()
        wait_ms(35)
        drag_samples.append(render_stats(root))
        if index == 3:
            save_window(window, drag_path)
    drag_object = root.property("dragObject")
    local_drag_position = drag_object.property("localDragPosition") if drag_object is not None else None
    QTest.mouseRelease(view._quick, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, final_point, 40)
    QApplication.processEvents()
    wait_ms(650)
    save_window(window, after_path)

    after_revision = model.revision
    after_scene_xy = (float(model.nodes[args.node].x), float(model.nodes[args.node].y))

    # --- Camera orbit with real right-button drag --------------------------
    empty = QPoint(args.width - 180, 150)
    if pick_name(root, empty):
        empty = QPoint(args.width // 2, 120)
    camera_before_orbit = camera_diag(root)
    QTest.mousePress(view._quick, Qt.MouseButton.RightButton, Qt.KeyboardModifier.NoModifier, empty, 30)
    for index in range(1, 6):
        QTest.mouseMove(view._quick, QPoint(empty.x() - 15 * index, empty.y() + 8 * index), 60)
        QApplication.processEvents()
        wait_ms(30)
    QTest.mouseRelease(
        view._quick,
        Qt.MouseButton.RightButton,
        Qt.KeyboardModifier.NoModifier,
        QPoint(empty.x() - 75, empty.y() + 40),
        30,
    )
    wait_ms(250)
    camera_after_orbit = camera_diag(root)
    save_window(window, orbit_path)

    # --- Shift-left panning -------------------------------------------------
    pan_start = QPoint(500, 160)
    camera_before_pan = camera_diag(root)
    QTest.mousePress(view._quick, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.ShiftModifier, pan_start, 30)
    for index in range(1, 5):
        QTest.mouseMove(view._quick, QPoint(pan_start.x() + 14 * index, pan_start.y() + 7 * index), 55)
        QApplication.processEvents()
        wait_ms(25)
    QTest.mouseRelease(
        view._quick,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.ShiftModifier,
        QPoint(pan_start.x() + 56, pan_start.y() + 28),
        30,
    )
    wait_ms(200)
    camera_after_pan = camera_diag(root)
    save_window(window, pan_path)

    # --- Real wheel event ---------------------------------------------------
    camera_before_wheel = camera_diag(root)
    local = QPointF(args.width / 2, args.height / 2)
    global_pos = QPointF(view._quick.mapToGlobal(QPoint(round(local.x()), round(local.y()))))
    wheel = QWheelEvent(
        local,
        global_pos,
        QPoint(0, 0),
        QPoint(0, 120),
        Qt.MouseButton.NoButton,
        Qt.KeyboardModifier.NoModifier,
        Qt.ScrollPhase.ScrollUpdate,
        False,
    )
    QApplication.sendEvent(view._quick, wheel)
    QApplication.processEvents()
    wait_ms(220)
    camera_after_wheel = camera_diag(root)
    save_window(window, zoom_path)

    # --- Standard view screenshots ----------------------------------------
    preset_paths: dict[str, str] = {}
    for index, preset in enumerate(("isometric", "front", "top", "side"), start=7):
        qml_call_void(root, "applyPreset", preset)
        wait_ms(260)
        path = args.output / f"{index:02d}_{preset}.png"
        save_window(window, path)
        preset_paths[preset] = str(path)

    # --- Detailed/simple toggle stress in the same live scene --------------
    rss_before_toggle = rss_mib()
    toggle_rss: list[float] = []
    for index in range(20):
        view._bridge.setDetailedAssetsEnabled(index % 2 == 1)
        QApplication.processEvents()
        wait_ms(35)
        toggle_rss.append(rss_mib())
    view._bridge.setDetailedAssetsEnabled(True)
    wait_ms(350)
    rss_after_toggle = rss_mib()

    # Compare primitive fallback versus detailed assets using the same camera.
    view._bridge.setDetailedAssetsEnabled(False)
    view.rotate_camera(0.20)
    wait_ms(350)
    stats_simple = render_stats(root)
    view._bridge.setDetailedAssetsEnabled(True)
    view.rotate_camera(-0.20)
    wait_ms(500)
    stats_detailed = render_stats(root)
    stats_final = stats_detailed
    qml_errors.extend(error.toString() for error in view._quick.errors() if error.toString() not in qml_errors)

    image_files = [initial_path, drag_path, after_path, orbit_path, pan_path, zoom_path] + [Path(p) for p in preset_paths.values()]
    screenshots = {path.name: image_metrics(path) for path in image_files}
    diffs = {
        "initial_to_drag": image_diff(initial_path, drag_path),
        "initial_to_after": image_diff(initial_path, after_path),
        "after_to_orbit": image_diff(after_path, orbit_path),
        "front_to_top": image_diff(Path(preset_paths["front"]), Path(preset_paths["top"])),
        "front_to_side": image_diff(Path(preset_paths["front"]), Path(preset_paths["side"])),
    }

    drag_frame_times = [float(item["frame_time_ms"]) for item in drag_samples if float(item["frame_time_ms"]) > 0]
    drag_render_times = [float(item["render_time_ms"]) for item in drag_samples if float(item["render_time_ms"]) > 0]

    checks = {
        "qml_ready": view._quick.status().name == "Ready" and not qml_errors,
        "real_rhi_renderer": "Software" not in renderer_api and "Unknown" not in renderer_api,
        "all_detailed_assets_loaded": assets["count"] == len(view._bridge.nodes) and assets["ready"] == assets["count"] and not assets["failed"],
        "node_projection_valid": 0 <= point.x() < args.width and 0 <= point.y() < args.height,
        "pick_hits_requested_node": picked == args.node,
        "drag_started_on_proxy": drag_press_ok,
        "drag_visual_position_changed": bool(local_drag_position) and (abs(float(local_drag_position.x()) - initial_world_xz[0]) > 5.0 or abs(float(local_drag_position.z()) - initial_world_xz[1]) > 5.0),
        "drag_committed_once": len(move_events) == 1 and move_events[0][0] == args.node,
        "model_revision_advanced": after_revision > initial_revision,
        "model_position_changed": math.hypot(after_scene_xy[0] - initial_scene_xy[0], after_scene_xy[1] - initial_scene_xy[1]) > 5.0,
        "drag_state_cleared": not bool(root.property("draggingDevice")) and str(root.property("dragId")) == "",
        "orbit_changed_camera": distance2d(camera_before_orbit, camera_after_orbit, "azimuth", "elevation") > 2.0,
        "pan_changed_camera": distance2d(camera_before_pan, camera_after_pan, "pivot_x", "pivot_y") > 2.0,
        "wheel_changed_zoom": abs(camera_after_wheel["distance"] - camera_before_wheel["distance"]) > 5.0,
        "screenshots_nonblank": all(metric["std"] > 8.0 and metric["nonwhite_ratio"] > 0.05 for metric in screenshots.values()),
        "drag_screenshot_changed": diffs["initial_to_drag"]["changed_ratio_gt2"] > 0.005,
        "post_commit_screenshot_changed": diffs["initial_to_after"]["changed_ratio_gt2"] > 0.005,
        "preset_views_differ": diffs["front_to_top"]["changed_ratio_gt2"] > 0.02 and diffs["front_to_side"]["changed_ratio_gt2"] > 0.02,
        "draw_call_budget": 0 < int(stats_final["draw_calls"]) <= 100,
        "vertex_budget": 0 < int(stats_final["draw_vertices"]) <= 100_000,
        "single_render_pass": int(stats_final["render_passes"]) <= 2,
        "detailed_drawcall_overhead_bounded": int(stats_detailed["draw_calls"]) - int(stats_simple["draw_calls"]) <= 60,
        "toggle_rss_growth_bounded": (rss_after_toggle - rss_before_toggle) < 64.0,
    }

    report = {
        "status": "PASS" if all(checks.values()) else "FAIL",
        "environment": {
            "platform": QApplication.platformName(),
            "graphics_api": renderer_api,
            "display": os.environ.get("DISPLAY", ""),
            "qsg_rhi_backend": os.environ.get("QSG_RHI_BACKEND", ""),
            "libgl_always_software": os.environ.get("LIBGL_ALWAYS_SOFTWARE", ""),
            "note": "Container/Xvfb numbers are a software-OpenGL CI baseline, not target-Windows GPU performance." if os.environ.get("LIBGL_ALWAYS_SOFTWARE") else "",
        },
        "checks": checks,
        "qml_errors": qml_errors,
        "assets": assets,
        "interaction": {
            "node": args.node,
            "projected_screen": [point.x(), point.y()],
            "pick_name": picked,
            "initial_scene_xy": list(initial_scene_xy),
            "after_scene_xy": list(after_scene_xy),
            "initial_world_xz": list(initial_world_xz),
            "move_events": move_events,
            "initial_revision": initial_revision,
            "after_revision": after_revision,
            "local_drag_world": None if local_drag_position is None else [float(local_drag_position.x()), float(local_drag_position.y()), float(local_drag_position.z())],
        },
        "camera": {
            "initial": initial_camera,
            "before_orbit": camera_before_orbit,
            "after_orbit": camera_after_orbit,
            "before_pan": camera_before_pan,
            "after_pan": camera_after_pan,
            "before_wheel": camera_before_wheel,
            "after_wheel": camera_after_wheel,
        },
        "render": {
            "final": stats_final,
            "simple_assets": stats_simple,
            "detailed_assets": stats_detailed,
            "detailed_minus_simple_draw_calls": int(stats_detailed["draw_calls"]) - int(stats_simple["draw_calls"]),
            "detailed_minus_simple_vertices": int(stats_detailed["draw_vertices"]) - int(stats_simple["draw_vertices"]),
            "drag_samples": drag_samples,
            "drag_frame_time_median_ms": statistics.median(drag_frame_times) if drag_frame_times else 0.0,
            "drag_frame_time_p95_ms": sorted(drag_frame_times)[max(0, math.ceil(len(drag_frame_times) * 0.95) - 1)] if drag_frame_times else 0.0,
            "drag_render_time_median_ms": statistics.median(drag_render_times) if drag_render_times else 0.0,
        },
        "memory": {
            "rss_before_toggle_mib": rss_before_toggle,
            "rss_after_toggle_mib": rss_after_toggle,
            "rss_delta_mib": rss_after_toggle - rss_before_toggle,
            "rss_samples_mib": toggle_rss,
        },
        "screenshots": {"files": [str(path) for path in image_files], "metrics": screenshots, "diffs": diffs},
    }
    report_path = args.output / "interaction_report.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    print(json.dumps(report, ensure_ascii=False, indent=2))
    window.close()
    view.deleteLater()
    window.deleteLater()
    QApplication.processEvents()
    gc.collect()
    return 0 if report["status"] == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
