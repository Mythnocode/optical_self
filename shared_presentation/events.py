"""Small per-instance event hooks for shared state outside Qt."""
from typing import Callable


class _BoundEvent:
    def __init__(self) -> None:
        self._slots: list[Callable] = []

    def connect(self, slot: Callable) -> None:
        self._slots.append(slot)

    def emit(self, *args, **kwargs) -> None:
        for slot in tuple(self._slots):
            slot(*args, **kwargs)


class Event:
    def __init__(self, *signature) -> None:
        self._name = ""

    def __set_name__(self, owner, name) -> None:
        self._name = f"_event_{name}"

    def __get__(self, instance, owner=None):
        if instance is None:
            return self
        if self._name not in instance.__dict__:
            instance.__dict__[self._name] = _BoundEvent()
        return instance.__dict__[self._name]
