from __future__ import annotations

from concurrent.futures import Future, ThreadPoolExecutor
from pathlib import Path
from threading import RLock
from typing import Any

from PySide6.QtCore import QObject, Signal

from help_runtime import HelpService, build_help_context


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
        service = self._get_service()
        context = build_help_context(page_id=page_id, project=project)
        answer = service.answer(
            question,
            context,
            use_llm=False,
            audience="professional" if audience == "professional" else "beginner",
        )
        return answer.model_dump(mode="python")

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
