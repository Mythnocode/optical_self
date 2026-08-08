
from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from time import monotonic
from typing import Any, Callable


@dataclass(slots=True)
class EditTransaction:
    object_id: str
    field_name: str
    before: Any
    after: Any
    started_at: float
    updated_at: float


class EditTransactionCoalescer:


    def __init__(
        self,
        commit: Callable[[EditTransaction], None],
        *,
        merge_window_s: float = 0.75,
        max_history: int = 200,
        checkpoint: Callable[[list[EditTransaction]], None] | None = None,
    ) -> None:
        self.commit_callback = commit
        self.merge_window_s = max(0.05, float(merge_window_s))
        self.max_history = max(1, int(max_history))
        self.checkpoint_callback = checkpoint
        self.current: EditTransaction | None = None
        self.history: list[EditTransaction] = []

    def update(self, object_id: str, field_name: str, before: Any, after: Any) -> None:
        now = monotonic()
        same = (
            self.current is not None
            and self.current.object_id == str(object_id)
            and self.current.field_name == str(field_name)
            and now - self.current.updated_at <= self.merge_window_s
        )
        if same:
            self.current.after = deepcopy(after)
            self.current.updated_at = now
            return
        self.commit_pending()
        self.current = EditTransaction(
            object_id=str(object_id),
            field_name=str(field_name),
            before=deepcopy(before),
            after=deepcopy(after),
            started_at=now,
            updated_at=now,
        )

    def commit_pending(self) -> EditTransaction | None:
        transaction = self.current
        self.current = None
        if transaction is None or transaction.before == transaction.after:
            return None
        self.history.append(transaction)
        self.commit_callback(transaction)
        self._trim_history()
        return transaction

    def cancel_pending(self) -> None:
        self.current = None

    def _trim_history(self) -> None:
        overflow = len(self.history) - self.max_history
        if overflow <= 0:
            return
        archived = self.history[:overflow]
        del self.history[:overflow]
        if self.checkpoint_callback is not None:
            self.checkpoint_callback(archived)


__all__ = ["EditTransaction", "EditTransactionCoalescer"]
