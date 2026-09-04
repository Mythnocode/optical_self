from __future__ import annotations

from dataclasses import asdict
from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any

from PySide6.QtCore import QObject, QStandardPaths, QTimer

from frontend_pyside.core.types import LensSurface, ProjectSnapshot


def _json_safe(value: Any):
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, dict):
        return {str(k): _json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(v) for v in value]
    try:
        import numpy as np
        if isinstance(value, np.generic):
            return value.item()
        if isinstance(value, np.ndarray):
            # 自动恢复只保存轻量工作状态，避免把大型结果数组写进恢复文件。
            return {"shape": list(value.shape), "dtype": str(value.dtype), "omitted": True}
    except Exception:
        pass
    return str(value)


class SessionRecoveryStore(QObject):
    """Debounced crash/workspace recovery for the current project.

    It never silently restores.  The shell asks the user whether to recover the last
    unsaved workspace.  Analysis arrays are not persisted; only project inputs,
    research context/findings and lightweight metrics are stored.
    """

    def __init__(self, project_context, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.project_context = project_context
        base = Path(QStandardPaths.writableLocation(QStandardPaths.StandardLocation.AppDataLocation))
        base.mkdir(parents=True, exist_ok=True)
        self.path = base / "workspace_recovery.json"
        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.setInterval(700)
        self.timer.timeout.connect(self.flush)
        for signal_name in (
            "project_changed", "simulation_project_payload_changed", "research_profile_changed",
            "research_context_changed", "findings_changed", "research_journal_changed", "dirty_changed",
        ):
            signal = getattr(project_context, signal_name, None)
            if signal is not None:
                signal.connect(self.schedule)

    def schedule(self, *_args) -> None:
        if bool(getattr(self.project_context, "dirty", False)):
            self.timer.start()
        else:
            self.clear()

    def flush(self) -> None:
        if not bool(getattr(self.project_context, "dirty", False)):
            self.clear()
            return
        project = self.project_context.project
        project_dict = asdict(project)
        # metrics 只保留轻量标量，正式大数组由各自缓存管理。
        project_dict["metrics"] = {
            str(k): _json_safe(v)
            for k, v in dict(getattr(project, "metrics", {}) or {}).items()
            if v is None or isinstance(v, (str, int, float, bool))
        }
        payload = {
            "saved_at": datetime.now(timezone.utc).isoformat(),
            "project": _json_safe(project_dict),
            "simulation_project_payload": _json_safe(self.project_context.simulation_project_payload),
            "research_profile": _json_safe(self.project_context.research_profile),
            "research_context": _json_safe(self.project_context.research_context),
            "findings": _json_safe(self.project_context.findings),
            "research_journal": _json_safe(self.project_context.research_journal),
            "design_revision": int(self.project_context.design_revision),
        }
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(self.path)

    def has_recovery(self) -> bool:
        return self.path.exists() and self.path.stat().st_size > 0

    def summary(self) -> str:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            project = dict(data.get("project", {}) or {})
            when = str(data.get("saved_at", ""))
            return f"{project.get('name', '未命名项目')} · {project.get('version', '')} · {when}"
        except Exception:
            return "发现上次未保存的工作状态"

    def restore(self) -> bool:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            raw = dict(data.get("project", {}) or {})
            surfaces = [LensSurface(**dict(item)) for item in raw.pop("surfaces", [])]
            project = ProjectSnapshot(surfaces=surfaces, **raw)
            self.project_context.set_project(project, dirty=True)
            self.project_context.set_simulation_project_payload(data.get("simulation_project_payload") or {})
            self.project_context.restore_research_state(
                research_profile=data.get("research_profile") or {},
                research_context=data.get("research_context") or {},
                findings=data.get("findings") or [],
                research_journal=data.get("research_journal") or [],
                design_revision=int(data.get("design_revision", self.project_context.design_revision)),
            )
            return True
        except Exception:
            return False

    def clear(self) -> None:
        self.timer.stop()
        try:
            self.path.unlink(missing_ok=True)
        except Exception:
            pass


__all__ = ["SessionRecoveryStore"]
