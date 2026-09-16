"""Small, UI-agnostic metadata object for one visible entry page."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class PageSpec:
    """Describe one page and its position in the owning primary entry."""

    module: str
    key: str
    kind: str
    menu_title: str
    menu_hint: str
    title: str
    subtitle: str


__all__ = ["PageSpec"]
