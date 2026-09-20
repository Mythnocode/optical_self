"""Page registry for the explainability primary entry."""

from .current_system import PAGE as CURRENT_SYSTEM_PAGE
from .global_contrib import PAGE as GLOBAL_CONTRIBUTION_PAGE
from .param_trend import PAGE as PARAMETER_TREND_PAGE


PAGES = (
    GLOBAL_CONTRIBUTION_PAGE,
    PARAMETER_TREND_PAGE,
    CURRENT_SYSTEM_PAGE,
)

__all__ = ["PAGES"]
