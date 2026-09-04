from __future__ import annotations


from shared_contracts.metrics import read_metric

class SimulationStatusMixin:
    def _refresh_submission_state(self) -> None:
        try:
            state = self.params.collect_state()
            planned = set(self.controller.planned_analyses(state, self.results.visible_result_keys()))
            cached = set(self.controller.cached_analyses(
                self.context.project.project,
                state,
                self.results.visible_result_keys(),
            ))
        except Exception:
            self.formal_button.setEnabled(True)
            self.formal_button.setText("开始计算")
            return

        missing = sorted(planned - cached)
        if self.session.dirty.is_dirty:
            self.formal_state.setText("⚠ 上一次结果 · 需更新")
            self.formal_state.setToolTip(self.session.dirty.reason)
            self.formal_state.set_tone("warning")
            self.formal_button.setEnabled(True)
            self.formal_button.setText("开始计算")
            self.results.set_result_stale(
                self.session.dirty.reason,
                version=str(getattr(self.context.project.project, "version", "")),
            )
        elif missing:
            self.formal_state.setText("— 当前视图未计算")
            self.formal_state.set_tone("warning")
            self.formal_button.setEnabled(True)
            self.formal_button.setText("补算当前视图")
            if self._formal_store is None:
                self.results.set_result_pending("当前视图尚未计算")
        else:
            self.formal_state.setText("✓ 正式结果 · 当前")
            self.formal_state.set_tone("success")
            self.formal_button.setText("结果已是最新")
            self.formal_button.setEnabled(False)

        if missing:
            self.formal_button.setToolTip("提交时仅运行缺少的分析：" + "、".join(missing))
        else:
            self.formal_button.setToolTip("当前物理参数与所需分析均已命中缓存")

    def _update_formal_metric_cards(self, metrics: dict) -> None:
        efficiency = read_metric(metrics, "coupling_efficiency")
        system_efficiency = read_metric(metrics, "system_efficiency")
        receiver_efficiency = read_metric(metrics, "receiver_efficiency")
        if system_efficiency is not None:
            self.cards["system_eff"].set_value(
                f"{100.0 * float(system_efficiency):.2f}", "%", note=""
            )
        if receiver_efficiency is not None:
            self.cards["receiver_eff"].set_value(
                f"{100.0 * float(receiver_efficiency):.2f}", "%", note=""
            )
        if efficiency is not None:
            self.cards["coupling_eff"].set_value(
                f"{100.0 * float(efficiency):.2f}", "%", note=""
            )
