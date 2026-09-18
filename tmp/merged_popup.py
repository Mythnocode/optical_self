class TeachingImagingCouplingPopup(QFrame):
    """成像与耦合：一个窗口里放成像预览和耦合数据。

    这两项本来各有一个窗口，但它们读的是同一次正式计算处方，放在一起才能
    对照着看：上面是接收面光斑预览，下面是效率数据（按钮式显示，与仿真页
    的耦合效率一致）。
    """

    calculateRequested = Signal()

    # 与仿真结果页一致的三项效率口径。
    EFFICIENCY_PILLS: tuple[tuple[str, str, tuple[str, ...]], ...] = (
        ("system", "系统效率", ("system_efficiency", "transmission_efficiency")),
        ("receiver", "端面接收效率", ("fiber_interface_efficiency", "receiver_efficiency", "receiving_efficiency")),
        ("total", "总耦合效率", ("total_coupling_efficiency", "total_efficiency", "coupling_efficiency")),
    )
    # 其余耦合指标直接列成一行，避免为每个值再开一个控件。
    DETAIL_METRICS: tuple[tuple[str, str, str], ...] = (
        ("coupling_efficiency", "模式耦合效率", "%"),
        ("mode_overlap_efficiency", "模式重叠效率", "%"),
        ("coupling_loss_db", "耦合损耗", "dB"),
    )

    def __init__(self, parent=None) -> None:
        super().__init__(parent, Qt.WindowType.Tool)
        self.setObjectName("TeachingImagingCouplingPopup")
        self.setWindowTitle("成像与耦合")
        self.setMinimumSize(460, 520)
        self.resize(500, 640)
        self._result_scene_revision: int | None = None
        self._scene_revision: int | None = None
        self._coupling_metrics: dict[str, Any] = {}
        self._imaging_metrics: dict[str, Any] = {}

        root = QVBoxLayout(self)
        root.setContentsMargins(14, 12, 14, 14)
        root.setSpacing(8)
        heading = QLabel("成像与耦合")
        heading.setObjectName("TeachingPopupTitle")
        root.addWidget(heading)

        action_row = QHBoxLayout()
        self.run_button = QPushButton("开始正式计算")
        self.run_button.setObjectName("teachingV2PrimaryButton")
        self.run_button.setMinimumHeight(38)
        self.run_button.setMinimumWidth(156)
        self.run_button.clicked.connect(self.calculateRequested.emit)
        action_row.addWidget(self.run_button)
        self.status = QLabel("尚未计算")
        self.status.setObjectName("TeachingPopupStatus")
        self.status.setWordWrap(True)
        action_row.addWidget(self.status, 1)
        root.addLayout(action_row)

        # 波动光学没有可信的完成百分比，用不确定进度条表示正在算。
        self.progress = QProgressBar(self)
        self.progress.setObjectName("TeachingAnalysisProgress")
        self.progress.setTextVisible(False)
        self.progress.setFixedHeight(8)
        self.progress.hide()
        root.addWidget(self.progress)

        imaging_title = QLabel("成像预览")
        imaging_title.setObjectName("PopupGroupTitle")
        root.addWidget(imaging_title)
        self.imaging_summary = QLabel("等待波动光学计算")
        self.imaging_summary.setObjectName("TeachingAnalysisSummary")
        self.imaging_summary.setWordWrap(True)
        root.addWidget(self.imaging_summary)
        self.imaging_visual = TeachingAnalysisVisual("spot", self)
        # 预览只是示意图，窗口要保持"小窗"尺寸，别让预览把耦合数据挤出去。
        self.imaging_visual.setMinimumHeight(168)
        self.imaging_visual.setMaximumHeight(186)
        root.addWidget(self.imaging_visual)

        coupling_title = QLabel("耦合数据")
        coupling_title.setObjectName("PopupGroupTitle")
        root.addWidget(coupling_title)
        pills = QHBoxLayout()
        pills.setSpacing(6)
        self.coupling_pills: dict[str, QLabel] = {}
        for key, title, _keys in self.EFFICIENCY_PILLS:
            label = QLabel(f"{title}：—")
            label.setObjectName("coup")
            label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            # 与仿真页一致：效率用按钮式标签显示，扫一眼就能比较。
            pills.addWidget(label, 1)
            self.coupling_pills[key] = label
        root.addLayout(pills)
        self.coupling_detail = QLabel("等待耦合计算")
        self.coupling_detail.setObjectName("HelperText")
        self.coupling_detail.setWordWrap(True)
        root.addWidget(self.coupling_detail)
        root.addStretch(1)

        self.notes = QLabel("成像与耦合使用同一份正式计算处方；先放好接收端再计算。")
        self.notes.setObjectName("TeachingPopupNotes")
        self.notes.setWordWrap(True)
        root.addWidget(self.notes)

    @staticmethod
    def _first_metric(metrics: dict[str, Any], keys: tuple[str, ...]) -> Any:
        for key in keys:
            if metrics.get(key) is not None:
                return metrics[key]
        return None

    def _refresh_pills(self) -> None:
        for key, title, keys in self.EFFICIENCY_PILLS:
            value = self._first_metric(self._coupling_metrics, keys)
            text = _format_teaching_metric(key, value, "%") if value is not None else "—"
            self.coupling_pills[key].setText(f"{title}：{text}")

    def set_scene_revision(self, revision: int) -> None:
        self._scene_revision = int(revision)
        if self._result_scene_revision is not None and self._result_scene_revision != int(revision):
            self.run_button.setEnabled(True)
            self.status.setText("场景已修改，当前指标已过期")
            self.imaging_summary.setText("成像结果已过期 · 请重新计算")
            self.coupling_detail.setText("耦合结果已过期 · 请重新计算")
            self.imaging_visual.set_metrics({}, available=False)

    def set_busy(self, busy: bool, message: str = "") -> None:
        self.run_button.setEnabled(not bool(busy))
        if busy:
            self.status.setText(str(message or "正在计算，界面仍可操作"))
            self.progress.setRange(0, 0)
            self.progress.show()
        elif message:
            self.status.setText(str(message))
            self.progress.hide()
            self.progress.setRange(0, 100)
            self.progress.setValue(0)
        else:
            self.progress.hide()
            self.progress.setRange(0, 100)
            self.progress.setValue(0)

    def set_running(self, analysis: str, *, done: bool = False) -> None:
        """显示正在算哪一项：合并后是两个分析，进度要说清楚。"""
        if done:
            self.set_busy(False, "正式计算完成")
            return
        title = str(TEACHING_ANALYSIS_INFO.get(str(analysis), {}).get("title") or analysis)
        self.set_busy(True, f"正在计算{title}…")

    def set_result(self, analysis: str, result: object) -> None:
        analysis = str(analysis)
        info = TEACHING_ANALYSIS_INFO.get(analysis, {})
        title = str(info.get("title") or analysis)
        artifacts = getattr(result, "artifacts", {}) or {}
        artifact = artifacts.get(analysis) if isinstance(artifacts, dict) else None
        artifact = dict(artifact or {})
        metrics = dict(artifact.get("metrics") or getattr(result, "metrics", {}) or {})
        status = str(artifact.get("status") or getattr(result, "status", "failed") or "failed")
        success = bool(getattr(result, "success", status == "completed"))
        completed = bool(success and status == "completed")
        scene_revision = getattr(result, "scene_revision", None)
        self._result_scene_revision = (
            int(scene_revision) if scene_revision is not None else self._scene_revision
        )
        self.run_button.setEnabled(True)
        self.progress.hide()
        self.progress.setRange(0, 100)
        self.progress.setValue(100)

        if analysis == "coupling":
            self._coupling_metrics = metrics if completed else {}
            self._refresh_pills()
            detail = [
                f"{label} {_format_teaching_metric(key, metrics.get(key), unit)}"
                for key, label, unit in self.DETAIL_METRICS
                if metrics.get(key) is not None
            ]
            if completed:
                self.coupling_detail.setText(" · ".join(detail) if detail else "已完成，但引擎未返回耦合指标")
            else:
                self.coupling_detail.setText("耦合计算未完成")
        else:
            self._imaging_metrics = metrics if completed else {}
            self.imaging_visual.set_metrics(metrics, available=completed)
            value = metrics.get("rms_spot_radius_um", metrics.get("rms_um"))
            self.imaging_summary.setText(
                f"RMS 光斑半径  {_format_teaching_metric('rms_spot_radius_um', value, 'μm')}"
                if completed
                else "成像计算未完成"
            )

        errors = [str(item).strip() for item in (artifact.get("errors") or getattr(result, "errors", ()) or ())]
        errors = [item for item in errors if item]
        raw_warnings = [
            str(item).strip() for item in (artifact.get("warnings") or getattr(result, "warnings", ()) or ())
        ]
        quality_needs_review = any(str(item).strip() for item in raw_warnings)
        comparison_note = str(artifact.get("comparison_note") or "教学场景正式计算")
        if errors:
            self.notes.setText(f"{title}：{errors[0]}")
        elif status == "missed":
            self.notes.setText(f"{title}：光束未命中接收端。")
        elif quality_needs_review:
            self.notes.setText(f"{comparison_note}；{title}计算质量：建议提高采样精度后复核。")
        else:
            self.notes.setText(f"{comparison_note}；{title}计算质量：正常。")
        if completed:
            elapsed = float(getattr(result, "elapsed_ms", 0.0) or 0.0)
            suffix = f" · {elapsed:.0f} ms" if elapsed > 0 else ""
            self.status.setText(f"{title}完成{suffix}")


