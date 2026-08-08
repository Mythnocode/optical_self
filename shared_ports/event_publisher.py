from typing import Any, Dict, Protocol


class EventPublisherPort(Protocol):
    def publish(self, event_name: str, payload: Dict[str, Any]) -> None: ...
