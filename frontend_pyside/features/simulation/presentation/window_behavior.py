from __future__ import annotations

from frontend_pyside.features.simulation.windows.lens_editor import LensEditorWindow


class SimulationWindowMixin:


    def _open_lens_editor(self) -> None:
        window = LensEditorWindow(self.context.project, self.window())
        self._child_windows.append(window)
        window.destroyed.connect(lambda *_: self._cleanup_child_windows())
        window.show()
        window.raise_()
        window.activateWindow()

    def _cleanup_child_windows(self) -> None:
        self._child_windows = [
            window for window in self._child_windows
            if window is not None and not window.isHidden()
        ]
