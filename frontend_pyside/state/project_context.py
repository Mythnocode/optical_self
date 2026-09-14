from __future__ import annotations

from copy import deepcopy
from datetime import datetime
import json
from dataclasses import replace
from uuid import uuid4

from PySide6.QtCore import QObject, Signal

from frontend_pyside.core.types import LensSurface, ProjectSnapshot
from frontend_pyside.presets.demo_780nm_four_lens import (
    DEFAULT_RECEIVER_MFD_UM,
    DEFAULT_WAVELENGTH_NM,
    FOUR_LENS_SURFACES,
    PROJECT_NAME,
    REFERENCE_COUPLING_EFFICIENCY,
    REFERENCE_TOTAL_COUPLING_EFFICIENCY,
    REFERENCE_GRID_SIZE,
)


def default_project() -> ProjectSnapshot:
    surfaces = [LensSurface(**dict(spec)) for spec in FOUR_LENS_SURFACES]
    return ProjectSnapshot(
        name=PROJECT_NAME,
        wavelength_nm=DEFAULT_WAVELENGTH_NM,
        receiver_mfd_um=DEFAULT_RECEIVER_MFD_UM,
        surfaces=surfaces,
        metrics={
            "reference_coupling_efficiency": REFERENCE_COUPLING_EFFICIENCY,
            "reference_total_coupling_efficiency": REFERENCE_TOTAL_COUPLING_EFFICIENCY,
            "reference_grid_size": REFERENCE_GRID_SIZE,
        },
    )


class ProjectContext(QObject):


    project_changed = Signal(object)
    metrics_changed = Signal(dict)
    dirty_changed = Signal(bool)
    version_changed = Signal(str)
    formal_result_changed = Signal(object)
    selection_changed = Signal(str, str)
    research_profile_changed = Signal(dict)
    simulation_project_payload_changed = Signal(dict)
    research_context_changed = Signal(dict)
    findings_changed = Signal(object)
    design_revision_changed = Signal(int)
    research_journal_changed = Signal(object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._project = default_project()
        self._dirty = False
        self._formal_result = None
        self._selected_element_id = ""
        self._selected_surface_id = ""
        self._research_profile: dict = {}
        self._simulation_project_payload: dict = {}
        self._simulation_physical_signature = ""
        self._research_context: dict = {}
        self._findings: list[dict] = []
        self._research_journal: list[dict] = []
        self._design_revision = 1

    @property
    def project(self) -> ProjectSnapshot:
        return self._project

    @property
    def dirty(self) -> bool:
        return self._dirty

    @property
    def formal_result(self):
        return self._formal_result

    @property
    def selected_element_id(self) -> str:
        return self._selected_element_id

    @property
    def selected_surface_id(self) -> str:
        return self._selected_surface_id

    @property
    def research_profile(self) -> dict:
        return deepcopy(self._research_profile)

    @property
    def simulation_project_payload(self) -> dict:

        return deepcopy(self._simulation_project_payload)

    @property
    def research_context(self) -> dict:
        snapshot = deepcopy(self._research_context)
        snapshot.setdefault("design_revision", self._design_revision)
        snapshot.setdefault("project_id", str(self._project.project_id))
        snapshot.setdefault("project_version", str(self._project.version))
        return snapshot

    @property
    def findings(self) -> list[dict]:
        return deepcopy(self._findings)

    @property
    def design_revision(self) -> int:
        return int(self._design_revision)

    @property
    def research_journal(self) -> list[dict]:
        return deepcopy(self._research_journal)

    def record_research_event(
        self,
        kind: str,
        title: str,
        details: dict | None = None,
        *,
        source: str = "平台",
        task_id: str = "",
        result_revision: int | None = None,
        dedupe_key: str = "",
    ) -> dict:
        """Append a lightweight, version-bound research event.

        This journal is not a chat transcript.  It records only events that change
        the research evidence chain: design changes, completed tasks, adopted models
        and formal-result updates.  Dense arrays stay in their own result stores.
        """
        event = {
            "event_id": f"event_{uuid4().hex}",
            "time": datetime.now().astimezone().isoformat(timespec="seconds"),
            "kind": str(kind or "event"),
            "title": str(title or "研究记录"),
            "source": str(source or "平台"),
            "task_id": str(task_id or ""),
            "design_revision": int(self._design_revision if result_revision is None else result_revision),
            "project_id": str(self._project.project_id),
            "project_version": str(self._project.version),
            "details": deepcopy(dict(details or {})),
            "dedupe_key": str(dedupe_key or ""),
        }
        key = event["dedupe_key"]
        if key:
            for index in range(len(self._research_journal) - 1, -1, -1):
                current = self._research_journal[index]
                if str(current.get("dedupe_key", "")) == key and int(current.get("design_revision", -1)) == event["design_revision"]:
                    event["event_id"] = str(current.get("event_id") or event["event_id"])
                    self._research_journal[index] = event
                    self.research_journal_changed.emit(self.research_journal)
                    return deepcopy(event)
        self._research_journal.append(event)
        self._research_journal = self._research_journal[-500:]
        self.research_journal_changed.emit(self.research_journal)
        return deepcopy(event)

    def set_project(self, project: ProjectSnapshot, *, dirty: bool = False) -> None:
        project.ensure_stable_ids()
        self._project = project
        self._formal_result = None
        self._research_profile = {}
        self._simulation_project_payload = {}
        self._simulation_physical_signature = ""
        self._research_context = {}
        self._findings = []
        self._research_journal = []
        self._design_revision += 1
        self._set_dirty(dirty)
        self.project_changed.emit(project)
        self.formal_result_changed.emit(None)
        self.research_profile_changed.emit({})
        self.simulation_project_payload_changed.emit({})
        self.research_context_changed.emit(self.research_context)
        self.findings_changed.emit([])
        self.research_journal_changed.emit([])
        self.design_revision_changed.emit(self._design_revision)

    def update_metrics(self, metrics: dict) -> None:
        self._project.metrics.update(dict(metrics or {}))
        snapshot = dict(self._project.metrics)
        self.metrics_changed.emit(snapshot)
        self.project_changed.emit(self._project)

    def replace_surfaces(self, surfaces: list[LensSurface], *, mark_dirty: bool = True) -> None:
        for surface in surfaces:
            surface.__post_init__()
        self._project.surfaces = list(surfaces)
        self._set_dirty(mark_dirty)
        self._bump_design_revision("镜片结构已修改")
        self._simulation_physical_signature = ""
        self.project_changed.emit(self._project)

    def upsert_custom_material(self, material: dict) -> None:
        payload = dict(material or {})
        name = str(payload.get("name") or "").strip()
        if not name:
            return
        payload["name"] = name
        items = [
            dict(item)
            for item in list(getattr(self._project, "custom_materials", ()) or ())
            if isinstance(item, dict) and str(item.get("name") or "").strip() != name
        ]
        items.append(payload)
        self._project.custom_materials = items
        self._set_dirty(True)
        self.project_changed.emit(self._project)

    def update_surface(self, surface_id: str, **changes) -> LensSurface | None:
        wanted = str(surface_id or "")
        for index, surface in enumerate(self._project.surfaces):
            if surface.surface_id != wanted:
                continue
            protected = {"surface_id", "element_id", "group_id"}
            values = {key: value for key, value in changes.items() if key not in protected}
            updated = replace(surface, **values)
            updated.surface_id = surface.surface_id
            updated.element_id = surface.element_id
            updated.group_id = surface.group_id
            self._project.surfaces[index] = updated
            self._set_dirty(True)
            self._bump_design_revision("镜片参数已修改")
            self._simulation_physical_signature = ""
            self.project_changed.emit(self._project)
            return deepcopy(updated)
        return None

    def update_pupil_radius(self, value: float, *, reason: str = "系统入瞳参数已修改") -> bool:
        """更新画布镜头组使用的系统入瞳半径，并广播统一项目变更。"""
        try:
            radius = float(value)
        except (TypeError, ValueError):
            return False
        if radius <= 0.0 or float(self._project.pupil_radius_mm) == radius:
            return False
        self._project.pupil_radius_mm = radius
        self._set_dirty(True)
        self._bump_design_revision(reason)
        self._simulation_physical_signature = ""
        self.project_changed.emit(self._project)
        return True

    def set_canvas_form_config(self, config: dict | None, *, reason: str = "系统参数已修改") -> bool:
        """保存画布胶囊的完整仿真表单状态。

        ``ProjectSnapshot`` 仍保持后端兼容的轻量结构；节点化表单中那些不适合
        塞入快照顶层的源、接收端和数值设置，挂在共享项目对象上供
        ``engine_bridge``/数据集任务统一序列化。这样画布表格、仿真和数据集
        不会各自持有一份失真的参数。
        """
        snapshot = deepcopy(dict(config or {}))
        previous = getattr(self._project, "_canvas_form_config", {})
        if snapshot == previous:
            return False
        self._project._canvas_form_config = snapshot
        self._set_dirty(True)
        self._bump_design_revision(reason)
        self._simulation_physical_signature = ""
        self.project_changed.emit(self._project)
        return True

    def reverse_element(self, element_id: str) -> bool:
        wanted = str(element_id or "")
        indices = [
            index
            for index, surface in enumerate(self._project.surfaces)
            if surface.element_id == wanted
        ]
        if len(indices) < 2:
            return False
        values = [self._project.surfaces[index] for index in indices][::-1]
        for target, value in zip(indices, values):
            self._project.surfaces[target] = value
        self._set_dirty(True)
        self._bump_design_revision("镜片方向已修改")
        self._simulation_physical_signature = ""
        self.project_changed.emit(self._project)
        return True

    def select(self, *, element_id: str = "", surface_id: str = "") -> None:
        element_id = str(element_id or "")
        surface_id = str(surface_id or "")
        if (
            element_id == self._selected_element_id
            and surface_id == self._selected_surface_id
        ):
            return
        self._selected_element_id = element_id
        self._selected_surface_id = surface_id
        self.selection_changed.emit(element_id, surface_id)

    def set_formal_result(self, result, *, metrics: dict | None = None) -> None:
        self._formal_result = result
        if metrics:
            self._project.metrics.update(dict(metrics))
            self.metrics_changed.emit(dict(self._project.metrics))
        self._set_dirty(False)
        self.formal_result_changed.emit(result)
        # A completed calculation adds evidence, not a prescription edit.
        # Emitting ``project_changed`` here discarded the synchronised teaching
        # calculation contract after every formal result.
        if isinstance(result, dict) and result:
            result_revision = result.get("design_revision", result.get("project_revision", result.get("revision", self._design_revision)))
            try:
                revision = int(result_revision)
            except (TypeError, ValueError):
                revision = self._design_revision
            result_metrics = dict(result.get("metrics", {}) or {})
            summary = {
                key: result_metrics.get(key, result.get(key))
                for key in ("coupling_efficiency", "system_efficiency", "converged", "status")
                if result_metrics.get(key, result.get(key)) is not None
            }
            self.record_research_event(
                "formal_result",
                "完成正式仿真",
                summary,
                source="正式仿真",
                result_revision=revision,
                dedupe_key="formal_result",
            )


    @staticmethod
    def _physical_payload_signature(payload: dict | None) -> str:
        """Return a stable signature for *physical* simulation inputs only.

        Analysis requests, plot selections and numerical/display settings must not make
        research findings stale.  Only fields that change the optical state belong here.
        """
        data = dict(payload or {})
        physical = {
            "source": data.get("source"),
            "receiver": data.get("receiver"),
            "surfaces": data.get("surfaces"),
            "object_distance_mm": data.get("object_distance_mm"),
            "image_distance_mm": data.get("image_distance_mm"),
            "pupil_radius_mm": data.get("pupil_radius_mm"),
            "aperture": data.get("aperture"),
            "field": data.get("field"),
        }
        return json.dumps(physical, ensure_ascii=False, sort_keys=True, default=str, separators=(",", ":"))

    def set_simulation_project_payload(self, payload: dict | None) -> None:
        snapshot = deepcopy(dict(payload or {}))
        if snapshot == self._simulation_project_payload:
            return
        previous_signature = self._simulation_physical_signature
        next_signature = self._physical_payload_signature(snapshot) if snapshot else ""
        self._simulation_project_payload = snapshot
        self._simulation_physical_signature = next_signature
        # 结果视图/分析项/采样显示设置变化不会让科研证据失效；只有物理输入变化才提升修订号。
        if previous_signature and next_signature and previous_signature != next_signature:
            self._bump_design_revision("当前仿真物理输入已修改")
        self.simulation_project_payload_changed.emit(deepcopy(snapshot))

    def update_research_profile(self, profile: dict | None = None, **changes) -> dict:

        merged = dict(self._research_profile)
        if profile is not None:
            merged.update(dict(profile))
        merged.update(changes)
        if merged == self._research_profile:
            return deepcopy(merged)
        self._research_profile = merged
        snapshot = deepcopy(merged)
        self.research_profile_changed.emit(snapshot)
        return snapshot

    def apply_parameter_changes(self, changes: dict[str, float], *, reason: str = "采用分析参数") -> bool:
        """Apply user-confirmed physical parameter changes to the shared project state.

        This is deliberately explicit: analysis pages may *offer* a value, but only a user
        action should call this method.  It updates the ProjectSnapshot where possible and
        the richer simulation payload for source/receiver/alignment fields.
        """
        changes = {str(path): float(value) for path, value in dict(changes or {}).items()}
        if not changes:
            return False
        payload = deepcopy(self._simulation_project_payload) or {}

        def current_value(path: str):
            if path == "source.wavelength_nm":
                return float(self._project.wavelength_nm)
            if path == "receiver.mode_field_diameter_x_um":
                return float(self._project.receiver_mfd_um)
            if path.startswith("receiver.") or path.startswith("source."):
                section, key = path.split(".", 1)
                source = payload.get(section, {}) if isinstance(payload, dict) else {}
                return source.get(key) if isinstance(source, dict) else None
            if path.startswith("surfaces["):
                try:
                    index = int(path.split("[", 1)[1].split("]", 1)[0])
                    field = path.split("].", 1)[1]
                except (ValueError, IndexError):
                    return None
                if 0 <= index < len(self._project.surfaces):
                    surface = self._project.surfaces[index]
                    if field == "distance_to_next_mm":
                        return float(surface.thickness_mm)
                    if field == "radius_mm":
                        return float(surface.radius_mm)
            return None

        before_values = {path: current_value(path) for path in changes}
        project_changed = False
        payload_changed = False

        def set_nested(section: str, key: str, value: float) -> None:
            nonlocal payload_changed
            target = payload.setdefault(section, {})
            if not isinstance(target, dict):
                target = {}; payload[section] = target
            if target.get(key) != value:
                target[key] = value; payload_changed = True

        for path, value in changes.items():
            if path == "source.wavelength_nm":
                if float(self._project.wavelength_nm) != value:
                    self._project.wavelength_nm = value; project_changed = True
                set_nested("source", "wavelength_nm", value)
                continue
            if path == "receiver.mode_field_diameter_x_um":
                if float(self._project.receiver_mfd_um) != value:
                    self._project.receiver_mfd_um = value; project_changed = True
                set_nested("receiver", "mode_field_diameter_x_um", value)
                continue
            if path.startswith("receiver."):
                set_nested("receiver", path.split(".", 1)[1], value)
                continue
            if path.startswith("source."):
                set_nested("source", path.split(".", 1)[1], value)
                continue
            if path.startswith("surfaces["):
                try:
                    index = int(path.split("[", 1)[1].split("]", 1)[0])
                    field = path.split("].", 1)[1]
                except (ValueError, IndexError):
                    continue
                if not 0 <= index < len(self._project.surfaces):
                    continue
                surface = self._project.surfaces[index]
                if field == "distance_to_next_mm":
                    if float(surface.thickness_mm) != value:
                        surface.thickness_mm = value; project_changed = True
                elif field == "radius_mm":
                    if float(surface.radius_mm) != value:
                        surface.radius_mm = value; project_changed = True
                if payload and isinstance(payload.get("surfaces"), list) and index < len(payload["surfaces"]):
                    target = payload["surfaces"][index]
                    if isinstance(target, dict) and target.get(field) != value:
                        target[field] = value; payload_changed = True
                continue

        if not (project_changed or payload_changed):
            return False
        self._set_dirty(True)
        self._bump_design_revision(reason)
        if project_changed:
            self.project_changed.emit(self._project)
        if payload_changed:
            payload.pop("fingerprint", None)
            self._simulation_project_payload = payload
            self._simulation_physical_signature = self._physical_payload_signature(payload)
            self.simulation_project_payload_changed.emit(deepcopy(payload))
        details = {
            path: {"before": before_values.get(path), "after": value}
            for path, value in changes.items()
            if before_values.get(path) != value
        }
        if details:
            self.record_research_event(
                "parameter_change",
                reason or "修改当前系统",
                details,
                source="用户确认",
                result_revision=self._design_revision,
            )
        return True

    def update_research_context(self, context: dict | None = None, **changes) -> dict:
        merged = dict(self._research_context)
        if context is not None:
            merged.update(dict(context))
        merged.update(changes)
        # 设计修订号由 ProjectContext 管理，页面不能自行覆盖。
        merged["design_revision"] = self._design_revision
        merged["project_id"] = str(self._project.project_id)
        merged["project_version"] = str(self._project.version)
        if merged == self._research_context:
            return self.research_context
        self._research_context = merged
        snapshot = self.research_context
        self.research_context_changed.emit(snapshot)
        return snapshot

    def publish_finding(self, finding: dict | None = None, **fields) -> dict:
        record = dict(finding or {})
        record.update(fields)
        record.setdefault("finding_id", f"finding_{uuid4().hex}")
        record.setdefault("source", "分析")
        record.setdefault("parameter", "")
        record.setdefault("status", "当前")
        record["design_revision"] = self._design_revision
        record["project_id"] = str(self._project.project_id)
        record["project_version"] = str(self._project.version)

        # 同一设计修订、同一来源、同一参数只保留最新一条，避免页面反复刷新堆积。
        source = str(record.get("source", ""))
        parameter = str(record.get("parameter", ""))
        scope = str(record.get("scope", ""))
        replace_index = None
        for index, current in enumerate(self._findings):
            if (
                int(current.get("design_revision", -1)) == self._design_revision
                and str(current.get("source", "")) == source
                and str(current.get("parameter", "")) == parameter
                and str(current.get("scope", "")) == scope
            ):
                replace_index = index
                break
        if replace_index is None:
            self._findings.append(record)
        else:
            # 保持 finding_id 稳定，外部详情窗口不会失去引用。
            record["finding_id"] = self._findings[replace_index].get("finding_id", record["finding_id"])
            self._findings[replace_index] = record
        self.findings_changed.emit(self.findings)
        return deepcopy(record)

    def verify_finding(self, finding_id: str) -> bool:
        wanted = str(finding_id or "")
        for record in self._findings:
            if str(record.get("finding_id", "")) != wanted:
                continue
            if int(record.get("design_revision", -1)) != self._design_revision:
                record["status"] = "需更新"
            else:
                record["status"] = "已验证"
            self.findings_changed.emit(self.findings)
            return True
        return False

    def findings_for(self, *, parameter: str | None = None, source: str | None = None, current_only: bool = False) -> list[dict]:
        rows = self.findings
        if parameter is not None:
            rows = [row for row in rows if str(row.get("parameter", "")) == str(parameter)]
        if source is not None:
            rows = [row for row in rows if str(row.get("source", "")) == str(source)]
        if current_only:
            rows = [row for row in rows if int(row.get("design_revision", -1)) == self._design_revision and str(row.get("status", "")) != "需更新"]
        return rows

    def _bump_design_revision(self, reason: str = "") -> None:
        self._design_revision += 1
        changed = False
        for record in self._findings:
            if str(record.get("status", "")) != "需更新":
                record["status"] = "需更新"
                if reason:
                    record["stale_reason"] = str(reason)
                changed = True
        self._research_context["design_revision"] = self._design_revision
        if reason:
            self._research_context["last_change"] = str(reason)
            self.record_research_event(
                "design_change",
                str(reason),
                {"new_revision": self._design_revision},
                source="系统",
                result_revision=self._design_revision,
            )
        self.design_revision_changed.emit(self._design_revision)
        self.research_context_changed.emit(self.research_context)
        if changed:
            self.findings_changed.emit(self.findings)

    def restore_research_state(
        self, *, research_profile: dict | None = None, research_context: dict | None = None,
        findings: list[dict] | None = None, research_journal: list[dict] | None = None,
        design_revision: int | None = None,
    ) -> None:
        """Restore debounced workspace metadata after an explicit user recovery action."""
        if design_revision is not None:
            self._design_revision = max(1, int(design_revision))
        self._research_profile = deepcopy(dict(research_profile or {}))
        self._research_context = deepcopy(dict(research_context or {}))
        self._research_context["design_revision"] = self._design_revision
        self._research_context["project_id"] = str(self._project.project_id)
        self._research_context["project_version"] = str(self._project.version)
        self._findings = [deepcopy(dict(row)) for row in (findings or []) if isinstance(row, dict)]
        self._research_journal = [deepcopy(dict(row)) for row in (research_journal or []) if isinstance(row, dict)][-500:]
        self.research_profile_changed.emit(deepcopy(self._research_profile))
        self.research_context_changed.emit(self.research_context)
        self.findings_changed.emit(self.findings)
        self.research_journal_changed.emit(self.research_journal)
        self.design_revision_changed.emit(self._design_revision)

    def clear_research_profile(self) -> None:
        if not self._research_profile:
            return
        self._research_profile = {}
        self.research_profile_changed.emit({})

    def mark_dirty(self) -> None:
        self._set_dirty(True)

    def save_version(self) -> str:
        try:
            number = int(str(self._project.version).lstrip("v")) + 1
        except ValueError:
            number = 2
        self._project.version = f"v{number}"
        self._set_dirty(False)
        self.version_changed.emit(self._project.version)
        self.project_changed.emit(self._project)
        return self._project.version

    def touch_version(self) -> None:
        self.save_version()

    def new_project_identity(self) -> None:
        self._project.project_id = f"project_{uuid4().hex}"
        self._bump_design_revision("项目标识已更新")
        self.project_changed.emit(self._project)

    def _set_dirty(self, dirty: bool) -> None:
        dirty = bool(dirty)
        if dirty == self._dirty:
            return
        self._dirty = dirty
        self.dirty_changed.emit(dirty)


__all__ = ["ProjectContext", "default_project"]
