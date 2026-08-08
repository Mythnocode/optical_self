from __future__ import annotations

from dataclasses import asdict, is_dataclass
from datetime import datetime
import json
import logging

from PySide6.QtCore import QSettings, QTimer, Signal
from PySide6.QtWidgets import QWidget

from frontend_pyside.core.types import LensSurface
from frontend_pyside.features.simulation.alignment import AlignmentSolution
from frontend_pyside.features.simulation.controller import SimulationController
from frontend_pyside.features.simulation.formal_result_store import FormalResultStore
from frontend_pyside.features.simulation.layout import build_simulation_layout
from frontend_pyside.features.simulation.simulation_session import SimulationSession
from frontend_pyside.features.simulation.workflow import SimulationPreviewWorkflow
from frontend_pyside.features.simulation.preview_scheduler import StagedPreviewScheduler
from frontend_pyside.features.simulation.request_fingerprint import canonical_json
from frontend_pyside.api.payloads import serialize_project
from frontend_pyside.shared.background import BackgroundPreparer
from frontend_pyside.shared.lifecycle import ManagedPageResources
from frontend_pyside.shared.settings import WorkspaceStateStore
from .presentation.mode_behavior import SimulationModeMixin
from .presentation.preview_behavior import SimulationPreviewMixin
from .presentation.formal_behavior import SimulationFormalMixin
from .presentation.selection_behavior import SimulationSelectionMixin
from .presentation.status_behavior import SimulationStatusMixin
from .presentation.window_behavior import SimulationWindowMixin


_logger = logging.getLogger(__name__)


class SimulationPage(SimulationModeMixin, SimulationPreviewMixin, SimulationFormalMixin, SimulationSelectionMixin, SimulationStatusMixin, SimulationWindowMixin, QWidget):


    navigateRequested = Signal(str)
    PREVIEW_DELAY_MS = 60

    def __init__(self, context, parent=None):
        super().__init__(parent)
        self.context = context
        self.lifecycle = ManagedPageResources(self)
        self.workspace_state = WorkspaceStateStore("simulation")
        self.settings = QSettings("Optical ML Platform", "OpticalFrontend")
        self._manual_preview_requested = False
        self._record_preview_usage = False
        self._auto_submit_scheduled = False
        self._missing_plot_retry_keys: set[tuple[str, tuple[str, ...]]] = set()
        self.multipath_mode = False
        self._work_mode = "unified"
        self._alignment_solution: AlignmentSolution | None = None
        self._formal_store: FormalResultStore | None = None
        self._teaching_snapshot_applied = False
        self._page_active = False
        self._main_splitter_initialized = False
        self._pending_formal_result: tuple[dict, dict] | None = None
        self._last_form_signature = ""
        self._last_geometry_signature = ""
        self._formal_result_received_perf = 0.0
        self._formal_workers: set[object] = set()
        self.session = SimulationSession()
        self._child_windows: list[QWidget] = []

        ui = build_simulation_layout(self, context)
        self.ui = ui
        self.model_badge = ui.model_badge
        self.multipath_button = ui.multipath_button
        self.multipath_toggle = ui.multipath_toggle
        self.auto_preview = ui.auto_preview
        self.preview_state = ui.preview_state
        self.formal_state = ui.formal_state
        self.main_splitter = ui.main_splitter
        self.editor = ui.editor
        self.params = ui.params
        self.results = ui.results
        self.cards = ui.cards
        self.apply_alignment_button = ui.apply_alignment_button
        self.diagnostic_text = ui.diagnostic_text
        self.formal_button = ui.formal_button
        self.lens_editor_button = ui.lens_editor_button
        self.save_parameters_button = ui.save_parameters_button
        self.import_teaching_button = ui.import_teaching_button
        self.teaching_button = ui.teaching_button
        self.detail_drawer = ui.detail_drawer
        self.result_splitter = ui.result_splitter

        self.preview_workflow = SimulationPreviewWorkflow(context.project)
        self.controller = SimulationController(context, self.preview_workflow, self)
        self.lifecycle.connect(self.controller.previewReady, self._display_preview)
        self.lifecycle.connect(self.controller.previewFailed, self._preview_failed)
        self.lifecycle.connect(self.controller.stateChanged, self._formal_state_changed)
        self.lifecycle.connect(self.controller.partialResultReady, self._display_partial_result)
        self.lifecycle.connect(self.controller.formalResultReady, self._display_formal_result)
        self.lifecycle.connect(self.controller.formalFailed, self._formal_failed)

        self.preview_scheduler = StagedPreviewScheduler(
            section_delay_ms=50,
            simplified_delay_ms=110,
            high_quality_delay_ms=500,
            parent=self,
        )
        self.preview_preparer = BackgroundPreparer(self)
        self.lifecycle.connect(self.preview_scheduler.sectionRequested, self._prepare_section_preview)
        self.lifecycle.connect(self.preview_scheduler.simplified3dRequested, self._prepare_interactive_preview)
        self.lifecycle.connect(self.preview_scheduler.highQuality3dRequested, self._prepare_high_quality_preview)
        self.lifecycle.connect(self.preview_preparer.completed, self._preview_prepared)
        self.lifecycle.connect(self.preview_preparer.failed, self._preview_prepare_failed)

        ui.preview_button.clicked.connect(self._manual_preview)
        ui.save_parameters_button.clicked.connect(self._save_workbench_parameters)
        ui.import_teaching_button.clicked.connect(self._apply_teaching_snapshot_if_available)
        ui.teaching_button.clicked.connect(self._open_teaching_with_current_parameters)
        ui.lens_editor_button.clicked.connect(self._open_lens_editor)
        if hasattr(self.editor, "fullEditorRequested"):
            self.editor.fullEditorRequested.connect(self._open_lens_editor)
        ui.formal_button.clicked.connect(self.submit_formal)
        ui.apply_alignment_button.clicked.connect(self._apply_alignment_solution)
        self.editor.changed.connect(self._geometry_changed)
        self.editor.surfaceSelected.connect(self._surface_selected_from_editor)
        self.editor.surfaceActivated.connect(self._surface_activated_from_editor)
        self.params.changed.connect(self._form_changed)
        self.results.visibleResultsChanged.connect(self._visible_results_changed)
        self.results.renderCompleted.connect(self._formal_plot_rendered)
        self.results.sectionOptionsChanged.connect(self._section_options_changed)
        self.results.surfaceSelected.connect(self._surface_selected_from_plot)
        self.results.surfaceActivated.connect(self._surface_activated_from_plot)
        self.results.recomputeRequested.connect(self.submit_formal)
        self.results.diagnosticsRequested.connect(self._open_detail_drawer)
        self.detail_drawer.visibilityChanged.connect(self._detail_drawer_visibility_changed)
        self.multipath_button.clicked.connect(self._enable_multipath_mode)
        self.multipath_toggle.toggled.connect(self._set_multipath_enabled)
        self.auto_preview.toggled.connect(self._auto_preview_toggled)
        self.main_splitter.splitterMoved.connect(self._remember_splitter)
        self.lifecycle.connect(context.services.ui_preferences.render_quality_changed, self.set_render_quality)

        self.auto_preview.setToolTip(
            "启用后合并连续输入：50 ms 更新二维截面，110 ms 更新简化三维，500 ms 后更新高质量预览；正式后端不会自动提交"
        )
        self.auto_preview.setChecked(
            self.settings.value("simulation/auto_preview", False, type=bool)
        )
        self.multipath_toggle.setChecked(
            self.settings.value("simulation/multipath_enabled", False, type=bool)
        )
        self.results.set_status(
            "结果按需加载：选择视图后自动读取缓存或补算缺失分析。",
            tone="info",
        )
        self.workspace_state.restore_splitter("main", self.main_splitter, [620, 980])
        self.workspace_state.restore_splitter("result", self.result_splitter, [1100, 0])
        self._normalize_main_splitter_state()
        self.set_render_quality(context.services.ui_preferences.render_quality)
        self._update_instant_efficiency_cards()
        self._capture_input_signatures()
        self._refresh_submission_state()
        self.lifecycle.single_shot(0, self._publish_active_simulation_project)
        self.lifecycle.single_shot(0, self._load_initial_result)

    def _publish_active_simulation_project(self, state=None) -> None:
        try:
            if state is None:
                state = self.params.collect_state()
            payload = serialize_project(self.context.project.project, state)
            self.context.project.set_simulation_project_payload(payload)
        except Exception:
            _logger.warning("无法同步当前仿真参数到其他工作区。", exc_info=True)

    def _prepare_section_preview(self, generation: int) -> None:
        self._prepare_preview_stage(generation, "section")

    def _prepare_interactive_preview(self, generation: int) -> None:
        self._prepare_preview_stage(generation, "interactive")

    def _prepare_high_quality_preview(self, generation: int) -> None:
        self._prepare_preview_stage(generation, "high")

    def _capture_input_signatures(self) -> None:

        try:
            state = self.params.collect_state()
            value = asdict(state) if is_dataclass(state) else dict(getattr(state, "__dict__", {}) or {})
            self._last_form_signature = canonical_json(value)
        except Exception:
            self._last_form_signature = ""
            _logger.warning("无法生成仿真参数签名，脏状态检测将退化。", exc_info=True)
        try:
            surfaces = []
            for surface in list(getattr(self.context.project.project, "surfaces", []) or []):
                surfaces.append(asdict(surface) if is_dataclass(surface) else dict(getattr(surface, "__dict__", {}) or {}))
            self._last_geometry_signature = canonical_json(surfaces)
        except Exception:
            self._last_geometry_signature = ""
            _logger.warning("无法生成光路结构签名，脏状态检测将退化。", exc_info=True)

    def _current_form_signature(self, state=None) -> str:
        if state is None:
            state = self.params.collect_state()
        value = asdict(state) if is_dataclass(state) else dict(getattr(state, "__dict__", {}) or {})
        return canonical_json(value)

    def _current_geometry_signature(self) -> str:
        surfaces = []
        for surface in list(getattr(self.context.project.project, "surfaces", []) or []):
            surfaces.append(asdict(surface) if is_dataclass(surface) else dict(getattr(surface, "__dict__", {}) or {}))
        return canonical_json(surfaces)

    def _parameter_state_dict(self) -> dict:
        try:
            state = self.params.collect_state()
        except Exception:
            _logger.exception("读取仿真参数状态失败，无法生成完整工作台快照。")
            raise
        if is_dataclass(state):
            return asdict(state)
        if isinstance(state, dict):
            return dict(state)
        values = getattr(state, "__dict__", None)
        return dict(values) if isinstance(values, dict) else {}

    def _build_workbench_snapshot(self) -> dict:
        project = self.context.project.project
        return {
            "source": "formal_workbench",
            "snapshot_version": 2,
            "saved_at": datetime.now().isoformat(timespec="seconds"),
            "project_name": str(getattr(project, "name", "光纤耦合方案")),
            "project_version": str(getattr(project, "version", "v1")),
            "wavelength_nm": float(getattr(project, "wavelength_nm", 808.0)),
            "receiver_mfd_um": float(getattr(project, "receiver_mfd_um", 5.6)),
            "surfaces": [asdict(surface) for surface in list(getattr(project, "surfaces", []) or [])],
            "parameter_state": self._parameter_state_dict(),
            "formal_metrics": dict(getattr(project, "metrics", {}) or {}),
        }

    def _save_workbench_parameters(self) -> dict | None:
        try:
            snapshot = self._build_workbench_snapshot()
            self.settings.setValue(
                "teaching/workbench_snapshot_json",
                json.dumps(snapshot, ensure_ascii=False),
            )
            self.settings.sync()
            if self.settings.status() != QSettings.Status.NoError:
                raise OSError(f"QSettings 写入失败：{self.settings.status().name}")
            self.context.project.update_research_profile(
                {
                    "active_snapshot_source": "workbench",
                    "workbench_snapshot": snapshot,
                    "shared_snapshot": snapshot,
                }
            )
        except Exception as exc:
            _logger.exception("保存仿真工作台参数失败")
            self.preview_state.setVisible(True)
            self.preview_state.set_tone("danger")
            self.preview_state.setText(f"参数保存失败：{exc}")
            return None
        self.preview_state.setVisible(True)
        self.preview_state.set_tone("success")
        self.preview_state.setText("参数已保存，可在教学中心查看")
        return snapshot

    def _open_teaching_with_current_parameters(self) -> None:
        if self._save_workbench_parameters() is not None:
            self.navigateRequested.emit("teaching")

    @staticmethod
    def _teaching_lenses_from_snapshot(snapshot: dict) -> list[dict]:
        nodes = list(snapshot.get("nodes", []) or [])
        lenses = [dict(node) for node in nodes if str(node.get("kind")) == "lens"]
        lenses.sort(key=lambda item: float(item.get("x", 0.0)))
        return lenses

    def _apply_teaching_snapshot_if_available(self) -> None:
        try:
            profile = self.context.project.research_profile
        except Exception:
            profile = {}
        if not isinstance(profile, dict):
            profile = {}
        snapshot = profile.get("teaching_snapshot") if str(profile.get("active_snapshot_source", "")) == "teaching" else None
        if not isinstance(snapshot, dict):
            raw = self.settings.value("teaching/shared_snapshot_json", "", type=str)
            if raw:
                try:
                    snapshot = json.loads(raw)
                except Exception:
                    _logger.warning("教学中心共享参数不是有效 JSON，已忽略。", exc_info=True)
                    snapshot = None
        if not isinstance(snapshot, dict):
            self.preview_state.setVisible(True)
            self.preview_state.setText("教学中心尚未保存可导入的参数")
            return
        lenses = self._teaching_lenses_from_snapshot(snapshot)
        if not lenses:
            return

        surfaces: list[LensSurface] = []
        for index, lens in enumerate(lenses):
            params = dict(lens.get("params", {}) or {})
            focal = max(1.0, float(params.get("focal_mm", 25.0)))
            
            
            radius = max(2.0, 1.04 * focal)
            next_x = float(lenses[index + 1].get("x", lens.get("x", 0.0) + 20.0)) if index + 1 < len(lenses) else float(lens.get("x", 0.0)) + 100.0
            gap_mm = max(0.5, min(40.0, (next_x - float(lens.get("x", 0.0))) / 20.0))
            group_id = str(lens.get("id") or f"L{index + 1}")
            surfaces.extend(
                [
                    LensSurface(f"L{index + 1} 前表面", radius, 2.0, "N-BK7", 3.0, group_id=group_id),
                    LensSurface(f"L{index + 1} 后表面", -radius, gap_mm, "AIR", 3.0, group_id=group_id),
                ]
            )
        project = self.context.project.project
        project.wavelength_nm = float(snapshot.get("wavelength_nm", project.wavelength_nm))
        project.receiver_mfd_um = 2.0 * float(snapshot.get("receiver_mode_radius_um", project.receiver_mfd_um / 2.0))
        self.context.project.replace_surfaces(surfaces, mark_dirty=True)
        self._teaching_snapshot_applied = True
        self.preview_state.setVisible(True)
        self.preview_state.setText("已导入教学中心参数，等待快速预览")

    def _load_initial_result(self) -> None:

        try:
            self.results.set_current_result("光路", notify=False)
            state = self.params.collect_state()
            restored = self.controller.restore_cached(
                self.context.project.project, state, self.results.visible_result_keys()
            )
            if restored is not None:
                body, submitted_project = restored
                self._display_formal_result(body, submitted_project)
                self.results.set_status("已恢复相同参数的正式缓存；未重新计算。", tone="success")
                return
            self.preview_scheduler.schedule(high_quality=False)
        except RuntimeError:
            
            return
        except Exception:
            
            self.preview_scheduler.schedule(high_quality=False)

    def set_render_quality(self, quality: str) -> None:
        if hasattr(self.results, "set_render_quality"):
            self.results.set_render_quality(str(quality))

    def _set_coupling_note(self, note: str) -> None:
        card = self.cards.get("coupling_eff")
        if card is None:
            return
        value = card.value_label.text() if hasattr(card, "value_label") else "—"
        unit = card.unit_label.text() if hasattr(card, "unit_label") else "%"
        card.set_value(value, unit, note=note)

    def _update_instant_efficiency_cards(self) -> None:

        try:
            from frontend_pyside.features.simulation.instant_metrics import estimate_efficiency

            state = self.params.collect_state()
            result = estimate_efficiency(self.context.project.project, state)
        except Exception:
            for key in ("system_eff", "receiver_eff", "coupling_eff"):
                card = self.cards.get(key)
                if card is not None:
                    card.set_value("—", "%", note="参数不完整")
            return
        high_precision = bool(
            getattr(self.params, "calc_high_precision_coupling", None)
            and self.params.calc_high_precision_coupling.isChecked()
        )
        note = "等待正式复场" if high_precision else "快速 Gaussian"
        self.cards["system_eff"].set_value(f"{100.0 * result.system:.2f}", "%", note="界面估计")
        self.cards["receiver_eff"].set_value(f"{100.0 * result.receiver:.2f}", "%", note="端面/传输")
        self.cards["coupling_eff"].set_value(f"{100.0 * result.total:.2f}", "%", note=note)

    def on_activated(self) -> None:
        self._page_active = True
        self.lifecycle.activated()
        self.controller.set_polling_allowed(True)
        self._apply_responsive_layout()
        
        
        if hasattr(self.results, "restore_cached_view"):
            self.results.restore_cached_view()
        pending, self._pending_formal_result = self._pending_formal_result, None
        if pending is not None:
            self._display_formal_result(*pending)
        else:
            self._refresh_submission_state()

    def on_deactivated(self) -> None:
        self._page_active = False
        self.preview_scheduler.cancel()
        self.controller.set_polling_allowed(False)
        self.lifecycle.deactivate()

    def _normalize_main_splitter_state(self) -> None:

        if not hasattr(self, "main_splitter"):
            return
        sizes = [int(value) for value in self.main_splitter.sizes()]
        total = max(sum(sizes), int(self.main_splitter.width()), int(self.width()), 1200)
        left = sizes[0] if len(sizes) == 2 else 0
        if left < 520:
            target = max(560, min(660, round(total * 0.40)))
            self.main_splitter.setSizes([target, max(520, total - target)])
        self._main_splitter_initialized = True

    def _apply_responsive_layout(self) -> None:
        if not hasattr(self, "main_splitter"):
            return
        
        
        
        if not self._main_splitter_initialized:
            self._normalize_main_splitter_state()
        width = max(1, self.width())
        if hasattr(self.results, "set_compact_navigation"):
            self.results.set_compact_navigation(width < 1320)

    def resizeEvent(self, event) -> None:  
        super().resizeEvent(event)
        self._apply_responsive_layout()

    def showEvent(self, event) -> None:
        self.on_activated()
        super().showEvent(event)

    def hideEvent(self, event) -> None:
        self.on_deactivated()
        super().hideEvent(event)

    def dispose_page(self) -> None:
        self.workspace_state.save_splitter("main", self.main_splitter)
        self.workspace_state.save_splitter("result", self.result_splitter)
        self.preview_scheduler.cancel()
        for window in list(self._child_windows):
            try:
                window.close()
                window.deleteLater()
            except RuntimeError:
                pass
        self._child_windows.clear()
        if hasattr(self.results, "dispose"):
            self.results.dispose()
        if hasattr(self.controller, "dispose"):
            self.controller.dispose()
        self.lifecycle.dispose()

    def _open_detail_drawer(self) -> None:
        self.detail_drawer.setVisible(True)
        self.result_splitter.setHandleWidth(6)
        self.detail_drawer.set_expanded(True)
        total = max(sum(self.result_splitter.sizes()), self.result_splitter.width(), 900)
        drawer_width = min(380, max(320, total // 3))
        self.result_splitter.setSizes([max(520, total - drawer_width), drawer_width])

    def _detail_drawer_visibility_changed(self, expanded: bool) -> None:
        if expanded:
            return
        total = max(sum(self.result_splitter.sizes()), self.result_splitter.width(), 900)
        self.detail_drawer.setVisible(False)
        self.result_splitter.setHandleWidth(0)
        self.result_splitter.setSizes([total, 0])

    @property
    def current_job_id(self) -> str:
        return self.controller.current_job_id
