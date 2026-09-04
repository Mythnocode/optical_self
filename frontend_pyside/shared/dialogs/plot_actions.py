from __future__ import annotations

from collections.abc import Mapping

from .result_viewers import ScientificPlotWindow


def open_plot_data(owner, title: str, data: Mapping | None, *, allow_follow: bool = False):
    payload = dict(data or {})
    if not payload or str(payload.get("kind", "empty")) == "empty":
        return None
    parent = owner.window() if hasattr(owner, "window") else owner
    window = ScientificPlotWindow(
        str(title or payload.get("title") or "图表"),
        payload,
        parent,
        follow=False,
        allow_follow=allow_follow,
    )
    windows = getattr(owner, "_scientific_plot_windows", None)
    if windows is None:
        windows = set()
        setattr(owner, "_scientific_plot_windows", windows)
    windows.add(window)
    window.destroyed.connect(lambda *_args, w=window, bucket=windows: bucket.discard(w))
    window.show()
    window.raise_()
    window.activateWindow()
    return window


def open_workspace_plot(owner, workspace):
    getter = getattr(workspace, "current_result", None)
    current = getter() if callable(getter) else None
    if not current:
        return None
    title, data = current
    return open_plot_data(owner, title, data, allow_follow=False)


__all__ = ["open_plot_data", "open_workspace_plot"]
