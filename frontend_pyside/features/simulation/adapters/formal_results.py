"""Compatibility facade for the shared presentation implementation."""
from shared_presentation.simulation.adapters.formal_results import __dict__ as _implementation
globals().update({key: value for key, value in _implementation.items() if not key.startswith("__")})

from shared_presentation.display_profile import use_display_profile
from frontend_pyside.shared.settings import SimulationNumericsProfileStore
from shared_presentation.simulation.adapters import formal_results as _shared_results

def formal_result_to_plots(*args, **kwargs):
    with use_display_profile(SimulationNumericsProfileStore().load()):
        return _shared_results.formal_result_to_plots(*args, **kwargs)

def preview_result_to_plots(*args, **kwargs):
    with use_display_profile(SimulationNumericsProfileStore().load()):
        return _shared_results.preview_result_to_plots(*args, **kwargs)
