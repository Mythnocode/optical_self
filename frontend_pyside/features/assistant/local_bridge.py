from __future__ import annotations

from concurrent.futures import Future, ThreadPoolExecutor
from pathlib import Path
from threading import RLock
from typing import Any

from PySide6.QtCore import QObject, Signal

from help_runtime import HelpService, build_help_context
from frontend_pyside.features.assistant.research_advisor import ResearchAdvisor


class LocalKnowledgeBridge(QObject):


    completed = Signal(str, object)
    failed = Signal(str, str)

    def __init__(self, project_root: str | Path | None = None, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.project_root = (
            Path(project_root).resolve()
            if project_root is not None
            else Path(__file__).resolve().parents[3]
        )
        self.resources_dir = self.project_root / "resources" / "help"
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="local-help")
        self._service: HelpService | None = None
        self._lock = RLock()
        self._closed = False
        self._advisor = ResearchAdvisor()

    def ask(
        self,
        key: str,
        *,
        question: str,
        page_id: str | None,
        project: dict[str, Any] | None,
        audience: str = "beginner",
    ) -> None:
        if self._closed:
            self.failed.emit(key, "本地知识库已关闭")
            return
        future = self._executor.submit(
            self._answer,
            question.strip(),
            page_id,
            project or {},
            audience,
        )
        future.add_done_callback(lambda item, request_key=key: self._finish(request_key, item))

    def _get_service(self) -> HelpService:
        with self._lock:
            if self._service is None:
                if not self.resources_dir.exists():
                    raise FileNotFoundError(f"未找到本地知识库：{self.resources_dir}")
                self._service = HelpService(self.resources_dir)
            return self._service

    def _answer(
        self,
        question: str,
        page_id: str | None,
        project: dict[str, Any],
        audience: str,
    ) -> dict[str, Any]:
        if not question:
            raise ValueError("问题不能为空")
        contextual = self._contextual_answer(question, page_id, project)
        if contextual is not None:
            return contextual
        service = self._get_service()
        context = build_help_context(page_id=page_id, project=project)
        answer = service.answer(
            question,
            context,
            use_llm=False,
            audience="professional" if audience == "professional" else "beginner",
        )
        return answer.model_dump(mode="python")

    @staticmethod
    def _tone_status(record: dict[str, Any]) -> str:
        status = str(record.get("status", "当前") or "当前")
        return status if status in {"当前", "已验证", "需更新"} else "当前"

    def _contextual_answer(
        self,
        question: str,
        page_id: str | None,
        project: dict[str, Any],
    ) -> dict[str, Any] | None:
        # ResearchAdvisor centralises evidence grading, model gating and page-aware
        # follow-up suggestions.  The local knowledge base remains the fallback for
        # definitions, navigation and general operation questions.
        return self._advisor.answer(question, page_id, project)

    @staticmethod
    def _current_model_metrics(project: dict[str, Any]) -> dict[str, Any]:
        registry = dict(project.get("registry", {}) or {})
        model = dict(registry.get("current_model", {}) or {})
        metrics = dict(model.get("metrics", {}) or {})
        test_metrics = dict(model.get("test_metrics", {}) or {})
        merged = dict(metrics)
        merged.update({key: value for key, value in test_metrics.items() if key not in merged})
        for key in ("r2", "mae", "rmse", "high_efficiency_mae"):
            if key in model and key not in merged:
                merged[key] = model[key]
        return merged

    @staticmethod
    def _completed_research_results(project: dict[str, Any]) -> list[dict[str, Any]]:
        snapshot = dict(project.get("research_results", {}) or {})
        rows: list[dict[str, Any]] = []
        records = dict(snapshot.get("tasks_by_id", {}) or {})
        results = dict(snapshot.get("results_by_task_id", {}) or {})
        if records or results:
            for task_id, result in results.items():
                task = dict(records.get(str(task_id), {}) or {})
                rows.append({
                    "id": str(task_id),
                    "name": str(task.get("name", task.get("title", ""))),
                    "kind": str(task.get("kind", task.get("type", ""))),
                    "status": str(task.get("status", "")),
                    "progress": task.get("progress", 0),
                    "result": result,
                })
            return rows
        # Backward compatibility with older payloads.
        legacy = snapshot.get("tasks", []) or []
        if isinstance(legacy, list):
            for task in legacy:
                if not isinstance(task, dict):
                    continue
                result = task.get("result")
                if result is None:
                    continue
                rows.append({
                    "name": str(task.get("name", "")),
                    "kind": str(task.get("kind", "")),
                    "status": str(task.get("status", "")),
                    "progress": task.get("progress", 0),
                    "result": result,
                })
        return rows

    @staticmethod
    def _result_excerpt(value: Any) -> str:
        if isinstance(value, dict):
            priority = (
                "best_efficiency", "best_value", "best_score", "coupling_efficiency",
                "system_efficiency", "rmse", "mae", "p05", "yield", "yield_rate",
                "mean", "std", "relative_rmse", "status",
            )
            bits = []
            for key in priority:
                item = value.get(key)
                if isinstance(item, (int, float, str)) and str(item) not in {"", "None"}:
                    bits.append(f"{key}={item}")
            if bits:
                return "，".join(bits[:6])
            for key, item in value.items():
                if isinstance(item, (int, float, str)):
                    bits.append(f"{key}={item}")
                if len(bits) >= 5:
                    break
            return "，".join(bits)
        return str(value)[:180]

    def _next_step_answer(self, page_id: str | None, project: dict[str, Any]) -> dict[str, Any]:
        findings = [dict(row) for row in project.get("findings", []) if isinstance(row, dict)]
        current = [row for row in findings if self._tone_status(row) in {"当前", "已验证"}]
        stale = [row for row in findings if self._tone_status(row) == "需更新"]
        context = dict(project.get("research_context", {}) or {})
        page_context = dict(project.get("page_context", {}) or {})
        formal = dict(project.get("formal_result", {}) or {})
        metrics = dict(project.get("metrics", {}) or {})
        completed_results = self._completed_research_results(project)
        task = str(context.get("current_task") or page_context.get("page") or "当前研究")
        current_view = str(page_context.get("current_view") or "").strip()

        model_metrics = self._current_model_metrics(project)
        r2 = model_metrics.get("r2", model_metrics.get("test_r2", metrics.get("r2", metrics.get("test_r2"))))
        poor_model = isinstance(r2, (int, float)) and float(r2) < 0.0
        formal_state = " ".join(
            str(value) for value in (
                page_context.get("formal_state"), formal.get("status"), formal.get("source")
            ) if value not in (None, "")
        )

        shap = [row for row in current if str(row.get("source", "")) == "SHAP"]
        scans = [row for row in current if str(row.get("source", "")) == "参数扫描"]
        tolerance = [row for row in current if "容差" in str(row.get("source", ""))]
        validation = [row for row in current if "验证" in str(row.get("source", ""))]
        optimization = [row for row in current if "优化" in str(row.get("source", ""))]
        task_optimizations = [row for row in completed_results if "优化" in (row.get("name", "") + row.get("kind", ""))]
        task_tolerances = [row for row in completed_results if "容差" in (row.get("name", "") + row.get("kind", ""))]
        task_scans = [row for row in completed_results if "扫描" in (row.get("name", "") + row.get("kind", ""))]
        task_validations = [row for row in completed_results if "验证" in (row.get("name", "") + row.get("kind", ""))]

        options: list[dict[str, str]] = []
        if "需更新" in formal_state or "过期" in formal_state:
            options.append({
                "title": "先更新正式结果",
                "explanation": "当前页面仍保留上一计算结果，但状态显示需要更新。先完成一次正式计算，后续参数研究、模型解释和验证会有更可靠的共同基准。",
            })

        if poor_model:
            options.append({
                "title": "先确认模型是否适合当前任务",
                "explanation": f"当前测试 R²={float(r2):.4f}<0。此时不宜让 SHAP 直接指导参数选择；可以先查看预测一致性/残差，或改用正式仿真做局部参数研究。",
            })
        elif shap:
            selected = str(page_context.get("selected_feature") or "").strip()
            if selected:
                names = selected
            else:
                top = [str(item) for item in (page_context.get("top_features") or []) if str(item).strip()]
                names = "、".join(top[:2]) or "、".join(
                    str(row.get("display_name") or row.get("parameter") or "参数") for row in shap[:2]
                )
            unverified = [row for row in shap if self._tone_status(row) != "已验证"]
            if unverified:
                options.append({
                    "title": "验证模型解释",
                    "explanation": f"你当前看到的 SHAP 结果把 {names} 识别为较重要因素，但这仍是模型解释。可用正式参数扫描检查真实响应趋势；平台不会自动替你缩小范围或加入优化变量。",
                })

        if scans:
            names = "、".join(str(row.get("display_name") or row.get("parameter") or "参数") for row in scans[:2])
            options.append({
                "title": "继续局部研究或优化",
                "explanation": f"已经完成 {names} 的正式扫描。可以在响应图上查看高效区域，再决定是否细化这个范围，或把该参数加入优化；已有范围只作为参考。",
            })
        if (optimization or task_optimizations) and not (tolerance or task_tolerances):
            options.append({
                "title": "检查系统稳定性",
                "explanation": "如果当前优化结果的名义性能已经满足目标，可以做容差分析，判断高效率是否依赖过于苛刻的装调条件。",
            })
        if not (validation or task_validations) and str(page_id or "") in {"simulation", "optimization", "machine_learning", "explainability"}:
            options.append({
                "title": "与外部参考比较",
                "explanation": "如果已有实验或公开文献数据，可以在实验验证中只导入参考值，让平台计算对应结果并比较误差；这用于验证平台，而不是替代当前研究。",
            })

        if not options:
            if str(page_id or "") == "simulation":
                options.extend([
                    {"title": "理解某个参数的影响", "explanation": "如果当前正式结果已经稳定，可以选择一个真正关心的变量做参数研究，观察响应曲线，而不是一次铺开所有参数。"},
                    {"title": "寻找更高性能参数", "explanation": "如果目标是提升耦合效率，可以进入参数优化；优化变量仍由你选择，平台不会根据已有分析自动替你决定。"},
                ])
            else:
                options.extend([
                    {"title": "查看当前正式结果", "explanation": "先确认当前系统的正式仿真结果和状态是否为“当前”；若结果仍需更新，优先重新计算。"},
                    {"title": "按研究目的继续", "explanation": "想理解规律可做参数研究；想提高性能可做优化；系统参数准备定型时再考虑容差或实验验证。"},
                ])

        view_text = f"你当前正在看“{current_view}”。" if current_view else ""
        if completed_results:
            latest = completed_results[0]
            excerpt = self._result_excerpt(latest.get("result"))
            if excerpt:
                view_text += f" 最近完整任务结果：{latest.get('name') or latest.get('kind')}（{excerpt}）。"
        if stale:
            warning = f"当前还有 {len(stale)} 条分析属于旧系统状态，已标记为“需更新”。这些结果只能作为历史参考，不应直接指导当前系统。"
        else:
            warning = "这些是可选研究路径，不会自动修改参数、启动任务或替你选择研究路线。"
        return {
            "status": "supported",
            "summary": f"你现在处于“{task}”。{view_text}下面按不同研究目的列出可选路径；没有唯一必须执行的下一步。",
            "findings": options[:3],
            "warnings": [warning],
        }

    def _reliability_answer(self, page_id: str | None, project: dict[str, Any]) -> dict[str, Any]:
        metrics = dict(project.get("metrics", {}) or {})
        findings = [dict(row) for row in project.get("findings", []) if isinstance(row, dict)]
        completed_results = self._completed_research_results(project)
        formal = dict(project.get("formal_result", {}) or {})
        stale = [row for row in findings if self._tone_status(row) == "需更新"]
        verified = [row for row in findings if self._tone_status(row) == "已验证"]
        notes: list[dict[str, str]] = []
        if formal:
            status = formal.get("status")
            converged = formal.get("converged")
            metrics_block = dict(formal.get("metrics", {}) or {}) if isinstance(formal.get("metrics"), dict) else {}
            coupling = metrics_block.get("coupling_efficiency", formal.get("coupling_efficiency"))
            detail = []
            if coupling is not None: detail.append(f"耦合效率 {coupling}")
            if converged is not None: detail.append("已收敛" if bool(converged) else "未收敛")
            if status: detail.append(f"状态 {status}")
            notes.append({"title": "正式仿真", "explanation": "；".join(detail) or "已有正式仿真结果。"})
        if completed_results:
            notes.append({"title": "完整任务结果", "explanation": f"当前助手可读取 {len(completed_results)} 个带结果的研究任务，不再只依据页面名称。"})
        if stale:
            notes.append({"title": "旧结果需要重算", "explanation": f"有 {len(stale)} 条分析结果来自之前的系统状态，现在不要直接用于判断当前系统。"})
        if verified:
            notes.append({"title": "已经确认的结果", "explanation": f"当前有 {len(verified)} 条结果已经确认，可以作为判断当前系统的参考。"})
        model_metrics = self._current_model_metrics(project)
        r2 = model_metrics.get("r2", model_metrics.get("test_r2", metrics.get("r2", metrics.get("test_r2"))))
        if isinstance(r2, (int, float)) and float(r2) < 0:
            notes.append({"title": "模型可靠性", "explanation": f"当前 R²={float(r2):.4f}<0，说明该模型在对应测试集上的表现较差，不宜单独依赖模型预测或 SHAP 结论。"})
        if not notes:
            notes.append({"title": "当前状态", "explanation": "现在还没有足够的信息判断结果是否可靠。建议先看完整仿真是否正常、模型测试是否够准，再综合判断。"})
        return {"status":"supported", "summary":"可靠性要和结果一起判断，不能只凭效率高低或一张图。", "findings":notes[:3], "warnings":[]}

    def _explain_current_answer(self, page_id: str | None, project: dict[str, Any]) -> dict[str, Any]:
        context = dict(project.get("research_context", {}) or {})
        page_context = dict(project.get("page_context", {}) or {})
        completed_results = self._completed_research_results(project)
        findings = [dict(row) for row in project.get("findings", []) if isinstance(row, dict)]
        current = [row for row in findings if self._tone_status(row) in {"当前", "已验证"}]
        items: list[dict[str, str]] = []
        for row in current[:3]:
            source = str(row.get("source") or "分析")
            name = str(row.get("display_name") or row.get("parameter") or "候选结果")
            evidence = dict(row.get("evidence", {}) or {})
            detail = []
            if "best_value" in evidence:
                detail.append(f"最佳值 {evidence['best_value']}")
            if "direction" in evidence:
                detail.append(f"方向 {evidence['direction']}")
            if "sensitivity" in evidence:
                detail.append(f"敏感度 {evidence['sensitivity']}")
            suffix = "；".join(detail) if detail else "可以打开对应分析图查看具体结果"
            items.append({"title": f"{name} · {source}", "explanation": suffix})
        current_plot = page_context.get("current_view_data") or page_context.get("current_plot") or page_context.get("shap_result")
        if current_plot:
            items.append({"title": f"当前图 · {page_context.get('current_view', '结果')}", "explanation": self._result_excerpt(current_plot) or "当前图的结构化数据已接入助手上下文。"})
        if completed_results:
            latest = completed_results[0]
            items.append({"title": f"最近完整结果 · {latest.get('name') or latest.get('kind')}", "explanation": self._result_excerpt(latest.get("result")) or "完整结果已接入助手上下文。"})
        if not items:
            items.append({"title":"当前结果", "explanation":"当前还没有可供解释的分析结果。先完成正式仿真、参数研究或 SHAP 后，我可以结合结果继续说明。"})
        return {"status":"supported", "summary": f"当前任务：{context.get('current_task', '未指定')}。下面只列出现在仍然适用的结果。", "findings":items, "warnings":[]}

    def _finish(self, key: str, future: Future) -> None:
        if self._closed:
            return
        try:
            result = future.result()
        except Exception as exc:  
            self.failed.emit(key, str(exc))
        else:
            self.completed.emit(key, result)

    def close(self) -> None:
        with self._lock:
            if self._closed:
                return
            self._closed = True
            service = self._service
            self._service = None
        if service is not None:
            try:
                service.close()
            except Exception:
                pass
        self._executor.shutdown(wait=False, cancel_futures=True)
