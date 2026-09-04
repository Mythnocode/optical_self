from __future__ import annotations

from dataclasses import asdict, is_dataclass
from datetime import datetime
import json
import logging

from PySide6.QtCore import QSettings, QTimer, Signal
from PySide6.QtWidgets import QWidget

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
from frontend_pyside.shared import layout_tokens as ui_layout
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
        self._last_published_simulation_payload: dict = {}
        self._applying_shared_payload = False
        self._formal_result_received_perf = 0.0
        self._formal_workers: set[object] = set()
        self._candidate_preview_changes: dict[str, float] = {}
        self._candidate_preview_label = ""
        self._candidate_preview_metrics: dict[str, float] = {}
        self._parameter_auto_collapsed = False
        self._parameter_user_override = False
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
        self.metric_frame = ui.metric_frame
        self.cards = ui.cards
        self.preview_banner = ui.preview_banner
        self.preview_banner_title = ui.preview_banner_title
        self.preview_banner_text = ui.preview_banner_text
        self.preview_apply_button = ui.preview_apply_button
        self.preview_clear_button = ui.preview_clear_button
        self.formal_progress_panel = ui.formal_progress_panel
        self.formal_progress_label = ui.formal_progress_label
        self.formal_progress_bar = ui.formal_progress_bar
        self.apply_alignment_button = ui.apply_alignment_button
        self.diagnostic_text = ui.diagnostic_text
        self.formal_button = ui.formal_button
        self.parameter_research_button = ui.parameter_research_button
        self.tolerance_analysis_button = ui.tolerance_analysis_button
        self.parameter_toggle_button = ui.parameter_toggle_button
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
        ui.parameter_research_button.clicked.connect(lambda: self._open_current_system_research("optimization.scan"))
        ui.tolerance_analysis_button.clicked.connect(lambda: self._open_current_system_research("optimization.tolerance"))
        ui.parameter_toggle_button.clicked.connect(self._toggle_parameter_panel)
        ui.preview_clear_button.clicked.connect(self.clear_candidate_preview)
        ui.preview_apply_button.clicked.connect(self.apply_candidate_preview)
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
        self.results.focusRequested.connect(self._focus_result_canvas)
        self.results.set_research_context(context.project.research_context)
        self.lifecycle.connect(context.project.research_context_changed, self.results.set_research_context)
        self.detail_drawer.visibilityChanged.connect(self._detail_drawer_visibility_changed)
        self.multipath_button.clicked.connect(self._enable_multipath_mode)
        self.multipath_toggle.toggled.connect(self._set_multipath_enabled)
        self.auto_preview.toggled.connect(self._auto_preview_toggled)
        self.main_splitter.splitterMoved.connect(self._remember_splitter)
        self.lifecycle.connect(context.services.ui_preferences.render_quality_changed, self.set_render_quality)
        self.lifecycle.connect(context.project.research_profile_changed, self._on_research_profile_changed)
        self.lifecycle.connect(context.project.simulation_project_payload_changed, self._shared_simulation_payload_changed)

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

    def show_candidate_preview(self, changes: dict, label: str = "候选") -> None:
        """Preview task candidate parameters without writing them into the current system."""
        clean = {str(k): float(v) for k, v in dict(changes or {}).items() if isinstance(v, (int, float))}
        if not clean:
            return
        self._candidate_preview_changes = clean
        self._candidate_preview_label = str(label or "候选")
        self._candidate_preview_metrics = {}
        self.preview_banner_title.setText(f"预览 · {self._candidate_preview_label}")
        self.preview_banner_text.setText("临时候选，仅用于快速观察；尚未写入当前系统，也不是正式仿真结果。")
        self.preview_banner.show()
        self.preview_state.setText("正在生成候选快速预览")
        self.preview_state.set_tone("warning")
        self.results.set_external_preview_state(True, self._candidate_preview_label)
        self.results.set_status("正在生成候选快速预览；正式结果不会被覆盖。", tone="warning")
        self.preview_scheduler.request_now(high_quality=True)

    def clear_candidate_preview(self) -> None:
        if not self._candidate_preview_changes:
            self.preview_banner.hide()
            return
        self._candidate_preview_changes = {}
        self._candidate_preview_label = ""
        self._candidate_preview_metrics = {}
        self.preview_banner.hide()
        self.results.set_external_preview_state(False)
        self._update_instant_efficiency_cards()
        self.results.set_status("已退出候选预览；恢复当前系统。", tone="info")
        self.preview_scheduler.request_now(high_quality=True)

    def apply_candidate_preview(self) -> None:
        changes = dict(self._candidate_preview_changes or {})
        if not changes:
            return
        apply_changes = getattr(self.context.project, "apply_parameter_changes", None)
        changed = bool(apply_changes(changes, reason=f"采用{self._candidate_preview_label or '候选'}参数")) if callable(apply_changes) else False
        self._candidate_preview_changes = {}
        self._candidate_preview_label = ""
        self._candidate_preview_metrics = {}
        self.preview_banner.hide()
        self.results.set_external_preview_state(False)
        self._update_instant_efficiency_cards()
        self.results.set_status("候选已应用到当前系统；请运行正式仿真验证。" if changed else "当前系统已处于该候选参数。", tone="success")
        self.preview_scheduler.request_now(high_quality=True)

    def _set_candidate_preview_metrics(self, metrics: dict) -> None:
        self._candidate_preview_metrics = dict(metrics or {})
        coupling = self._candidate_preview_metrics.get("coupling_efficiency")
        if isinstance(coupling, (int, float)):
            self.cards["coupling_eff"].set_value(f"{100.0 * float(coupling):.2f}", "%", note="候选预览")
        self.formal_state.setText("候选预览 · 待正式验证")
        self.formal_state.set_tone("warning")

    def handle_assistant_action(self, action: dict) -> None:
        payload = dict(action or {})
        target = str(payload.get("target", "") or "")
        extra = dict(payload.get("payload") or {})
        if target == "simulation.formal":
            self.formal_button.setFocus()
            self.formal_button.setToolTip("检查当前参数后，由你确认是否开始正式计算。")
        elif target == "simulation.parameters":
            if not self.params.isVisible():
                self._toggle_parameter_panel()
            self.params.setFocus()
        elif target == "simulation.lens_editor":
            self._open_lens_editor()
        elif target == "simulation.view":
            view = str(extra.get("view") or "光路")
            self.results.set_current_result(view)
            self.results.setFocus()
        elif target == "simulation.result_catalogue":
            self.results.setFocus()
            QTimer.singleShot(0, self.results.analysis_selector.showPopup)
        elif target in {"simulation.parameter_research", "optimization.scan"}:
            self._open_current_system_research("optimization.scan", extra)
        elif target in {"simulation.tolerance", "optimization.tolerance"}:
            self._open_current_system_research("optimization.tolerance", extra)
        elif target in {"simulation.current", "simulation.result"}:
            self.results.setFocus()
        elif target == "simulation.focus":
            self._focus_result_canvas()


    def _open_current_system_research(self, target: str, payload: dict | None = None) -> None:
        """Open scan/tolerance as research attached to the current simulation system.

        The implementation is intentionally reused from the existing research task
        container, but the ownership/navigation is Simulation.  This keeps the
        persistent formal-result workbench visible and prevents parameter research
        or tolerance from re-expanding the primary Optimization workspace.
        """
        self._publish_active_simulation_project()
        # Parameter research and tolerance are owned by Simulation even though
        # they reuse the mature research task container.  Pass that ownership
        # explicitly so tolerance defaults to the current formal system rather
        # than silently inheriting a stale optimisation candidate.
        task_payload = dict(payload or {})
        task_payload.setdefault("research_owner", "simulation")
        shell = self.window()
        opener = getattr(shell, "_open_optimization_task", None)
        if callable(opener):
            opener(str(target), task_payload)
            return
        # Standalone/page tests do not have MainWindow.  Lazily create the same
        # modeless task window so the entry remains functional in isolation.
        try:
            from frontend_pyside.features.optimization.task_window import OptimizationTaskWindow
            window = OptimizationTaskWindow(self.context, self.window())
            window.set_target(str(target), task_payload)
            window.previewRequested.connect(self.show_candidate_preview)
            window.previewCleared.connect(self.clear_candidate_preview)
            self._child_windows.append(window)
            window.bring_to_front()
        except Exception:
            _logger.exception("无法打开当前系统研究任务")

    def assistant_action_target_widget(self, action: dict):
        target = str(dict(action or {}).get("target", "") or "")
        if target == "simulation.formal":
            return self.formal_button
        if target in {"simulation.current", "simulation.result", "simulation.focus"}:
            return self.results
        return self

    def _focus_result_canvas(self) -> None:
        shell = self.window()
        focus = getattr(shell, "set_workspace_focus", None)
        if callable(focus):
            focus(True)

    def _publish_active_simulation_project(self, state=None) -> None:
        try:
            if state is None:
                state = self.params.collect_state()
            payload = serialize_project(self.context.project.project, state)
            self._last_published_simulation_payload = dict(payload)
            self.context.project.set_simulation_project_payload(payload)
        except Exception:
            _logger.warning("无法同步当前仿真参数到其他工作区。", exc_info=True)

    def _shared_simulation_payload_changed(self, payload: dict) -> None:
        incoming = dict(payload or {})
        if not incoming or incoming == self._last_published_simulation_payload or self._applying_shared_payload:
            return
        self._applying_shared_payload = True
        try:
            self.params.apply_project_payload(incoming)
            # 镜片结构由 ProjectContext.project_changed 更新；这里仅同步光源/光纤/系统表单。
        finally:
            self._applying_shared_payload = False

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
            "project_name": str(getattr(project, "name", "光纤耦合系统")),
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

    def _on_research_profile_changed(self, profile: dict) -> None:
        self.params.apply_numerics_profile()
        if self._page_active:
            self._maybe_auto_import_teaching_snapshot(profile)

    def _maybe_auto_import_teaching_snapshot(self, profile: dict | None = None) -> None:
        snapshot_profile = dict(profile or self.context.project.research_profile or {})
        if not snapshot_profile.get("pending_teaching_import"):
            return
        if self._apply_teaching_snapshot_if_available(silent=True):
            self.context.project.update_research_profile(pending_teaching_import=False)

    def _open_teaching_with_current_parameters(self) -> None:
        if self._save_workbench_parameters() is not None:
            self.navigateRequested.emit("teaching")

    def _apply_teaching_snapshot_if_available(self, *, silent: bool = False) -> bool:
        from frontend_pyside.features.simulation.teaching_import import (
            receiver_payload_from_teaching_snapshot,
            resolve_teaching_snapshot,
            source_payload_from_teaching_snapshot,
            surfaces_from_teaching_lenses,
            teaching_lenses_from_snapshot,
        )

        try:
            profile = self.context.project.research_profile
        except Exception:
            profile = {}
        raw = self.settings.value("teaching/shared_snapshot_json", "", type=str)
        snapshot = resolve_teaching_snapshot(profile if isinstance(profile, dict) else {}, raw)
        if snapshot is None:
            if not silent:
                self.preview_state.setVisible(True)
                self.preview_state.set_tone("warning")
                self.preview_state.setText("教学中心尚未保存可导入的参数")
            return False
        lenses = teaching_lenses_from_snapshot(snapshot)
        if not lenses:
            if not silent:
                self.preview_state.setVisible(True)
                self.preview_state.set_tone("warning")
                self.preview_state.setText("教学快照中没有可导入的透镜")
            return False

        project = self.context.project.project
        project.wavelength_nm = float(snapshot.get("wavelength_nm", project.wavelength_nm))
        project.receiver_mfd_um = 2.0 * float(
            snapshot.get("receiver_mode_radius_um", project.receiver_mfd_um / 2.0)
        )
        self.context.project.replace_surfaces(surfaces_from_teaching_lenses(lenses), mark_dirty=True)
        self.params.apply_project_payload(
            {
                "source": source_payload_from_teaching_snapshot(snapshot),
                "receiver": receiver_payload_from_teaching_snapshot(snapshot),
            }
        )
        self._publish_active_simulation_project()
        self._teaching_snapshot_applied = True
        self.preview_state.setVisible(True)
        self.preview_state.set_tone("success")
        self.preview_state.setText(
            "已导入教学参数（含光纤装调）"
            if silent
            else "已导入教学参数（含光纤装调）；可点击预览或开始计算"
        )
        self._update_instant_efficiency_cards()
        self._geometry_changed()
        if self.auto_preview.isChecked():
            self.preview_scheduler.schedule(high_quality=False)
        return True

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
            from frontend_pyside.features.teaching.preview_metrics import beam_radius_from_project_metrics

            state = self.params.collect_state()
            project = self.context.project.project
            beam_radius = beam_radius_from_project_metrics(project)
            result = estimate_efficiency(
                project,
                state,
                beam_radius_at_receiver_um=beam_radius,
            )
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
        # 三个效率只显示数值；结果来源/新旧状态统一由 formal_state 表达，避免卡片尾注挤压。
        self.cards["system_eff"].set_value(f"{100.0 * result.system:.2f}", "%", note="")
        self.cards["receiver_eff"].set_value(f"{100.0 * result.receiver:.2f}", "%", note="")
        self.cards["coupling_eff"].set_value(f"{100.0 * result.total:.2f}", "%", note="")
        if self.session.dirty.is_dirty:
            self.formal_state.setText("⚠ 需更新")
            self.formal_state.set_tone("warning")
        else:
            self.formal_state.setText("● 快速预览")
            self.formal_state.set_tone("info")

    def on_activated(self) -> None:
        self._page_active = True
        self.lifecycle.activated()
        self.controller.set_polling_allowed(True)
        self._apply_responsive_layout()
        self._maybe_auto_import_teaching_snapshot()
        
        
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
        total = max(sum(sizes), int(self.main_splitter.width()), int(self.width()), 900)
        if not self.params.isVisible():
            self.main_splitter.setSizes([0, total])
            self._main_splitter_initialized = True
            return
        left = sizes[0] if len(sizes) == 2 else 0
        # 参数栏只容纳常用输入。完整 Surface/高级数值设置不靠加宽侧栏解决。
        target = max(ui_layout.SIM_PARAMETER_MIN_WIDTH, min(ui_layout.SIM_PARAMETER_MAX_WIDTH, round(total * 0.23)))
        if left < ui_layout.SIM_PARAMETER_MIN_WIDTH or left > ui_layout.SIM_PARAMETER_MAX_WIDTH + 12:
            self.main_splitter.setSizes([target, max(520, total - target)])
        self._main_splitter_initialized = True

    def _toggle_parameter_panel(self) -> None:
        show = not self.params.isVisible()
        self._parameter_user_override = True
        self._parameter_auto_collapsed = False
        if show:
            self.params.show()
            total = max(sum(self.main_splitter.sizes()), self.main_splitter.width(), self.width(), 900)
            target = max(ui_layout.SIM_PARAMETER_MIN_WIDTH, min(ui_layout.SIM_PARAMETER_MAX_WIDTH, round(total * 0.23)))
            self.main_splitter.setSizes([target, max(520, total - target)])
            self.parameter_toggle_button.setText("收起参数")
        else:
            self.params.hide()
            self.parameter_toggle_button.setText("显示参数")
        self._main_splitter_initialized = True

    def _apply_responsive_layout(self) -> None:
        if not hasattr(self, "main_splitter"):
            return
        
        
        
        if not self._main_splitter_initialized:
            self._normalize_main_splitter_state()
        width = max(1, self.width())
        # Very narrow windows keep the engineering canvas usable by collapsing the
        # parameter navigator. The user can still explicitly reopen it.
        if width < 980 and self.params.isVisible() and not self._parameter_user_override:
            self.params.hide()
            self.parameter_toggle_button.setText("显示参数")
            self._parameter_auto_collapsed = True
        elif width >= 1040 and self._parameter_auto_collapsed and not self._parameter_user_override:
            self.params.show()
            self.parameter_toggle_button.setText("收起参数")
            self._parameter_auto_collapsed = False

        # QSettings can contain an old zero-width left pane. If parameters are visible,
        # recover a compact usable width instead of preserving the old wide pane.
        sizes = [int(value) for value in self.main_splitter.sizes()]
        if self.params.isVisible():
            total = max(sum(sizes), self.main_splitter.width(), self.width(), 900)
            target = max(ui_layout.SIM_PARAMETER_MIN_WIDTH, min(ui_layout.SIM_PARAMETER_MAX_WIDTH, round(total * 0.23)))
            if len(sizes) != 2 or abs(sizes[0] - target) > 22:
                self.main_splitter.setSizes([target, max(520, total - target)])
        compact = width < 1320
        if hasattr(self.results, "set_compact_navigation"):
            self.results.set_compact_navigation(compact)
        # 结果状态三项始终归在同一条结果带；窄屏只收紧最小宽度，不再通过隐藏/弹窗表达。
        for key in ("coupling_eff", "system_eff", "receiver_eff"):
            card = self.cards.get(key)
            if card is not None:
                card.setVisible(True)
                card.setMinimumWidth(104 if compact else 126)

    def resizeEvent(self, event) -> None:  
        super().resizeEvent(event)
        self._apply_responsive_layout()

    def showEvent(self, event) -> None:
        self.on_activated()
        super().showEvent(event)

    def hideEvent(self, event) -> None:
        self.on_deactivated()
        super().hideEvent(event)

    def assistant_context(self) -> dict:
        data = self.results.current_data() if hasattr(self, "results") else {}
        return {
            "page": "仿真系统",
            "current_view": self.results.current_key() if hasattr(self, "results") else "",
            "view_source": str(data.get("source", "")) if isinstance(data, dict) else "",
            "view_kind": str(data.get("kind", "")) if isinstance(data, dict) else "",
            "formal_state": self.formal_state.text() if hasattr(self, "formal_state") else "",
            "metrics": {
                key: card.value_label.text() if hasattr(card, "value_label") else ""
                for key, card in getattr(self, "cards", {}).items()
            },
            "current_view_data": data if isinstance(data, dict) else {},
            "project_metrics": dict(getattr(self.context.project.project, "metrics", {}) or {}),
        }

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
