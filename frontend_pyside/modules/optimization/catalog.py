"""Page registry for the optimization primary entry."""

from .result import PAGE as RESULT_PAGE
from .scan import PAGE as SCAN_PAGE
from .variables import PAGE as VARIABLES_PAGE


PAGES = (SCAN_PAGE, VARIABLES_PAGE, RESULT_PAGE)

__all__ = ["PAGES"]
