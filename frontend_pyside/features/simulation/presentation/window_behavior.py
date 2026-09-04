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
        alive = []
        for window in list(self._child_windows):
            if window is None:
                continue
            try:
                if not window.isHidden():
                    alive.append(window)
            except RuntimeError:
                # WA_DeleteOnClose destroys the C++ window before Qt emits all
                # queued cleanup callbacks; stale Python wrappers are discarded.
                continue
        self._child_windows = alive
